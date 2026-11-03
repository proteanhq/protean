"""Tests for ExpectedVersionError auto-retry at the @handle decorator level.

The @handle wrapper catches ExpectedVersionError and retries with exponential
backoff before propagating to the subscription retry/DLQ pipeline.
"""

import logging
import warnings
from enum import Enum
from unittest.mock import patch
from uuid import uuid4

import pytest

from protean.core.aggregate import BaseAggregate, apply
from protean.core.command import BaseCommand
from protean.core.command_handler import BaseCommandHandler
from protean.core.event import BaseEvent
from protean.core.event_handler import BaseEventHandler
from protean.core.unit_of_work import UnitOfWork
from protean.exceptions import (
    ConfigurationError,
    ExpectedVersionError,
    TransactionError,
)
from protean.fields import Identifier, String
from protean.utils import mixins
from protean.utils.globals import current_domain
from protean.utils.mixins import (
    _VERSION_RETRY_DEFAULTS,
    _get_version_retry_config,
    handle,
)

# ---------------------------------------------------------------------------
# Domain elements shared across tests
# ---------------------------------------------------------------------------


class UserStatus(Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class UserRegistered(BaseEvent):
    user_id: Identifier(required=True)
    name: String(max_length=50, required=True)
    email: String(required=True)


class UserActivated(BaseEvent):
    user_id: Identifier(required=True)


class UserRenamed(BaseEvent):
    user_id: Identifier(required=True)
    name: String(required=True, max_length=50)


class User(BaseAggregate):
    user_id: Identifier(identifier=True)
    name: String(max_length=50, required=True)
    email: String(required=True)
    status: String(choices=UserStatus)

    @classmethod
    def register(cls, user_id: str, name: str, email: str) -> "User":
        user = cls(user_id=user_id, name=name, email=email)
        user.raise_(UserRegistered(user_id=user_id, name=name, email=email))
        return user

    def activate(self) -> None:
        self.raise_(UserActivated(user_id=self.user_id))

    def change_name(self, name: str) -> None:
        self.raise_(UserRenamed(user_id=self.user_id, name=name))

    @apply
    def registered(self, event: UserRegistered) -> None:
        self.user_id = event.user_id
        self.name = event.name
        self.email = event.email
        self.status = UserStatus.INACTIVE.value

    @apply
    def activated(self, _: UserActivated) -> None:
        self.status = UserStatus.ACTIVE.value

    @apply
    def renamed(self, event: UserRenamed) -> None:
        self.name = event.name


class RenameUser(BaseCommand):
    user_id: Identifier(required=True)
    name: String(required=True, max_length=50)


class UserCommandHandler(BaseCommandHandler):
    @handle(RenameUser)
    def rename(self, command: RenameUser) -> None:
        repo = current_domain.repository_for(User)
        user = repo.get(command.user_id)
        user.change_name(command.name)
        repo.add(user)


class UserEventHandler(BaseEventHandler):
    @handle(UserRegistered)
    def on_registered(self, event: UserRegistered) -> None:
        pass  # Side-effect placeholder


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(User, event_sourced=True)
    test_domain.register(UserRegistered, part_of=User)
    test_domain.register(UserActivated, part_of=User)
    test_domain.register(UserRenamed, part_of=User)
    test_domain.register(RenameUser, part_of=User)
    # `UserCommandHandler` is NOT registered here — tests that define
    # their own `RenameUser` handler would otherwise collide with it.
    # The one test that needs `UserCommandHandler` registers it itself.
    test_domain.register(UserEventHandler, part_of=User)
    test_domain.init(traverse=False)


def _create_user(test_domain) -> str:
    """Helper to create a user and return the identifier."""
    identifier = str(uuid4())
    with UnitOfWork():
        repo = test_domain.repository_for(User)
        user = User.register(user_id=identifier, name="John", email="john@example.com")
        repo.add(user)
    return identifier


# ---------------------------------------------------------------------------
# Configuration tests
# ---------------------------------------------------------------------------


class TestVersionRetryDefaults:
    """Verify default configuration values."""

    def test_default_values(self):
        assert _VERSION_RETRY_DEFAULTS["enabled"] is True
        assert _VERSION_RETRY_DEFAULTS["max_retries"] == 3
        assert _VERSION_RETRY_DEFAULTS["base_delay_seconds"] == 0.05
        assert _VERSION_RETRY_DEFAULTS["max_delay_seconds"] == 1.0

    @pytest.mark.parametrize(
        "overrides",
        [
            None,
            {
                "enabled": False,
                "max_retries": 5,
                "base_delay_seconds": 0.1,
                "max_delay_seconds": 2.0,
            },
            {"max_retries": 10},
        ],
        ids=["domain-defaults", "all-keys", "one-key"],
    )
    def test_config_read_from_active_domain(self, test_domain, caplog, overrides):
        """The active domain's values win; a missing key falls back to its default."""
        if overrides is not None:
            test_domain.config["server"]["version_retry"] = overrides
        caplog.set_level(logging.WARNING, logger="protean.utils.mixins")

        config = _get_version_retry_config()

        assert config == {**_VERSION_RETRY_DEFAULTS, **(overrides or {})}
        assert [r for r in caplog.records if r.name == "protean.utils.mixins"] == []

    @pytest.fixture
    def fresh_warnings(self, monkeypatch):
        """Forget the ``[server]`` tables earlier tests already warned about."""
        monkeypatch.setattr(mixins, "_warned_version_retry_configs", set())

    @pytest.mark.parametrize(
        "bad_config",
        [
            {"max_retries": "three"},
            {"base_delay_seconds": None},
            # TOML accepts ``inf``; ``int(inf)`` raises OverflowError
            {"max_retries": float("inf")},
            "not-a-table",
        ],
    )
    def test_invalid_config_falls_back_to_defaults_with_warning(
        self, test_domain, caplog, fresh_warnings, bad_config
    ):
        """A value that cannot be read falls back to defaults and warns."""
        test_domain.config["server"]["version_retry"] = bad_config
        caplog.set_level(logging.WARNING, logger="protean.utils.mixins")

        config = _get_version_retry_config()

        assert config == _VERSION_RETRY_DEFAULTS
        records = [r for r in caplog.records if r.name == "protean.utils.mixins"]
        assert len(records) == 1
        assert records[0].levelno == logging.WARNING
        message = records[0].getMessage()
        assert message.startswith("Invalid `server.version_retry` configuration (")
        assert message.endswith("); using the defaults")
        if isinstance(bad_config, dict):
            assert f"version_retry = {bad_config!r}" in message
        else:
            assert "`server.version_retry` is a str, not a table" in message
        # A conversion failure carries its traceback; a non-table has none
        assert bool(records[0].exc_info) == isinstance(bad_config, dict)

    def test_warning_leaves_the_rest_of_the_server_table_out(
        self, test_domain, caplog, fresh_warnings
    ):
        """Other `[server]` keys can hold credentials; the warning omits them."""
        test_domain.config["server"]["admin_token"] = "s3cr3t-token"
        test_domain.config["server"]["version_retry"] = {"max_retries": "three"}
        caplog.set_level(logging.WARNING, logger="protean.utils.mixins")

        assert _get_version_retry_config() == _VERSION_RETRY_DEFAULTS

        records = [r for r in caplog.records if r.name == "protean.utils.mixins"]
        assert len(records) == 1
        assert "s3cr3t-token" not in records[0].getMessage()
        assert "s3cr3t-token" not in caplog.text

    def test_invalid_config_warns_once(self, test_domain, caplog, fresh_warnings):
        """The config is read on every handler call; the warning is not."""
        test_domain.config["server"]["version_retry"] = {"max_retries": "three"}
        caplog.set_level(logging.WARNING, logger="protean.utils.mixins")

        for _ in range(3):
            assert _get_version_retry_config() == _VERSION_RETRY_DEFAULTS

        records = [r for r in caplog.records if r.name == "protean.utils.mixins"]
        assert len(records) == 1

    @pytest.mark.parametrize("error", [RuntimeError, AttributeError, TypeError])
    def test_unexpected_config_error_propagates(self, test_domain, error):
        """Only conversion and non-table errors fall back; others surface."""

        class BrokenTable(dict):
            def get(self, *args, **kwargs):
                raise error("config error")

        test_domain.config["server"] = BrokenTable()

        with pytest.raises(error, match="config error"):
            _get_version_retry_config()

    def test_non_table_server_section_falls_back_with_warning(
        self, test_domain, caplog, fresh_warnings
    ):
        test_domain.config["server"] = "redis://user:s3cr3t@host"
        caplog.set_level(logging.WARNING, logger="protean.utils.mixins")

        assert _get_version_retry_config() == _VERSION_RETRY_DEFAULTS

        records = [r for r in caplog.records if r.name == "protean.utils.mixins"]
        assert len(records) == 1
        message = records[0].getMessage()
        assert "`server` is a str, not a table" in message
        assert "s3cr3t" not in message

    def test_config_falls_back_when_no_domain_active(self, test_domain):
        """Falls back to defaults when no domain context is active."""
        from protean.utils.globals import _domain_context_stack

        # Temporarily pop the domain context to make current_domain falsy
        ctx = _domain_context_stack.pop()
        try:
            # No "outside of domain context" warning either
            with warnings.catch_warnings():
                warnings.simplefilter("error")
                config = _get_version_retry_config()
            assert config == _VERSION_RETRY_DEFAULTS
        finally:
            _domain_context_stack.push(ctx)

    def test_domain_config_has_version_retry_section(self, test_domain):
        """The default domain config includes version_retry under server."""
        server_config = test_domain.config.get("server", {})
        vr = server_config.get("version_retry", {})
        assert "enabled" in vr
        assert "max_retries" in vr
        assert "base_delay_seconds" in vr
        assert "max_delay_seconds" in vr


# ---------------------------------------------------------------------------
# Basic retry behavior tests
# ---------------------------------------------------------------------------


class TestRetryOnVersionError:
    """Test that @handle retries on ExpectedVersionError."""

    @patch("protean.utils.mixins.time.sleep")
    def test_succeeds_on_first_attempt(self, mock_sleep, test_domain, caplog):
        """No retry and no retry log when the handler succeeds immediately."""
        test_domain.register(UserCommandHandler, part_of=User)
        test_domain.init(traverse=False)

        identifier = _create_user(test_domain)

        command = RenameUser(user_id=identifier, name="Jane")
        enriched = test_domain._enrich_command(command, True)
        with caplog.at_level(logging.DEBUG, logger="protean.utils.mixins"):
            UserCommandHandler._handle(enriched)

        # Verify the rename happened
        repo = test_domain.repository_for(User)
        user = repo.get(identifier)
        assert user.name == "Jane"
        mock_sleep.assert_not_called()
        assert [r for r in caplog.records if "Version conflict" in r.message] == []

    @pytest.mark.parametrize("conflicts", [1, 2])
    @patch("protean.utils.mixins.time.sleep")
    def test_retries_on_version_error_then_succeeds(
        self, mock_sleep, test_domain, caplog, conflicts
    ):
        """Each conflict sleeps once, logs the retry, and reruns the handler
        in a fresh UoW; the final run's return value reaches the caller."""
        attempt_count = 0

        class ConflictHandler(BaseCommandHandler):
            @handle(RenameUser)
            def rename(self, command: RenameUser) -> str:
                nonlocal attempt_count
                attempt_count += 1
                if attempt_count <= conflicts:
                    raise ExpectedVersionError(
                        "Wrong expected version: 0 (Stream: test, Stream Version: 1)"
                    )
                repo = current_domain.repository_for(User)
                user = repo.get(command.user_id)
                user.change_name(command.name)
                repo.add(user)
                return "renamed"

        test_domain.register(ConflictHandler, part_of=User)
        test_domain.init(traverse=False)

        identifier = _create_user(test_domain)

        command = RenameUser(user_id=identifier, name="Jane")
        enriched = test_domain._enrich_command(command, True)
        with caplog.at_level(logging.DEBUG, logger="protean.utils.mixins"):
            result = ConflictHandler._handle(enriched)

        assert result == "renamed"
        assert attempt_count == conflicts + 1
        assert mock_sleep.call_count == conflicts
        retry_logs = [r for r in caplog.records if "Version conflict" in r.message]
        assert len(retry_logs) == conflicts
        for number, record in enumerate(retry_logs, start=1):
            assert f"retrying ({number}/3)" in record.message
        assert test_domain.repository_for(User).get(identifier).name == "Jane"

    @pytest.mark.parametrize(
        "errors",
        [
            [ValueError("business rule violation")],
            [
                ExpectedVersionError("conflict"),
                RuntimeError("unexpected error on retry"),
            ],
        ],
        ids=["first-attempt", "after-a-version-conflict"],
    )
    @patch("protean.utils.mixins.time.sleep")
    def test_other_error_propagates_without_retry(
        self, mock_sleep, test_domain, errors
    ):
        """An error that is not a version conflict propagates at once, even
        when it is raised by a retry."""
        attempt_count = 0

        class BadHandler(BaseCommandHandler):
            @handle(RenameUser)
            def rename(self, command: RenameUser) -> None:
                nonlocal attempt_count
                attempt_count += 1
                raise errors[attempt_count - 1]

        test_domain.register(BadHandler, part_of=User)
        test_domain.init(traverse=False)

        identifier = _create_user(test_domain)

        command = RenameUser(user_id=identifier, name="Jane")
        enriched = test_domain._enrich_command(command, True)

        with pytest.raises(type(errors[-1]), match=str(errors[-1])):
            BadHandler._handle(enriched)

        assert attempt_count == len(errors)


# ---------------------------------------------------------------------------
# Disabled retry tests
# ---------------------------------------------------------------------------


class TestRetryDisabled:
    """Test that retry can be disabled via configuration."""

    @pytest.mark.parametrize(
        "key, value",
        [("enabled", False), ("max_retries", 0)],
        ids=["enabled-flag", "zero-retries"],
    )
    @patch("protean.utils.mixins.time.sleep")
    def test_disabled_retry_raises_on_first_conflict(
        self, mock_sleep, test_domain, key, value
    ):
        """``enabled = false`` or ``max_retries = 0`` bypasses retry entirely."""
        attempt_count = 0

        class FailHandler(BaseCommandHandler):
            @handle(RenameUser)
            def rename(self, command: RenameUser) -> None:
                nonlocal attempt_count
                attempt_count += 1
                raise ExpectedVersionError("conflict")

        test_domain.register(FailHandler, part_of=User)
        test_domain.init(traverse=False)

        # Set config AFTER init to avoid any reset
        test_domain.config["server"]["version_retry"][key] = value

        identifier = _create_user(test_domain)

        command = RenameUser(user_id=identifier, name="Jane")
        enriched = test_domain._enrich_command(command, True)

        with pytest.raises(ExpectedVersionError):
            FailHandler._handle(enriched)

        assert attempt_count == 1
        mock_sleep.assert_not_called()


# ---------------------------------------------------------------------------
# Backoff timing tests
# ---------------------------------------------------------------------------


class TestExponentialBackoff:
    """Verify exponential backoff delays and capping."""

    @pytest.mark.parametrize(
        "overrides, delays",
        [
            # Default: 3 retries = 4 total attempts, 3 sleeps
            ({}, [0.05, 0.1, 0.2]),
            ({"max_retries": 1}, [0.05]),
            (
                {
                    "max_retries": 4,
                    "base_delay_seconds": 0.1,
                    "max_delay_seconds": 10.0,
                },
                [0.1, 0.2, 0.4, 0.8],
            ),
            (
                {"max_retries": 5, "base_delay_seconds": 0.5, "max_delay_seconds": 1.0},
                [0.5, 1.0, 1.0, 1.0, 1.0],
            ),
        ],
        ids=["defaults", "one-retry", "exponential", "capped-at-max"],
    )
    @patch("protean.utils.mixins.time.sleep")
    def test_exhausted_retries_raise_after_backoff_delays(
        self, mock_sleep, test_domain, overrides, delays
    ):
        """Delays follow 2^attempt * base_delay, never exceed max_delay_seconds,
        and the last conflict propagates once the retries run out."""
        attempt_count = 0

        class FailHandler(BaseCommandHandler):
            @handle(RenameUser)
            def rename(self, command: RenameUser) -> None:
                nonlocal attempt_count
                attempt_count += 1
                raise ExpectedVersionError("persistent version conflict")

        test_domain.register(FailHandler, part_of=User)
        test_domain.init(traverse=False)

        # Set config AFTER init
        test_domain.config["server"]["version_retry"].update(overrides)

        identifier = _create_user(test_domain)

        command = RenameUser(user_id=identifier, name="Jane")
        enriched = test_domain._enrich_command(command, True)

        with pytest.raises(ExpectedVersionError, match="persistent version conflict"):
            FailHandler._handle(enriched)

        assert attempt_count == len(delays) + 1
        assert [call.args[0] for call in mock_sleep.call_args_list] == pytest.approx(
            delays
        )


# ---------------------------------------------------------------------------
# Event handler retry tests
# ---------------------------------------------------------------------------


class TestEventHandlerRetry:
    """Verify retry works for event handlers, not just command handlers."""

    @patch("protean.utils.mixins.time.sleep")
    def test_event_handler_retries_on_version_error(self, mock_sleep, test_domain):
        """Event handler @handle wrapper retries on version conflict."""
        attempt_count = 0

        class RetryEventHandler(BaseEventHandler):
            @handle(UserRegistered)
            def on_registered(self, event: UserRegistered) -> None:
                nonlocal attempt_count
                attempt_count += 1
                if attempt_count == 1:
                    raise ExpectedVersionError("concurrent modification")

        test_domain.register(RetryEventHandler, part_of=User)
        test_domain.init(traverse=False)

        event = UserRegistered(
            user_id=str(uuid4()), name="John", email="john@example.com"
        )
        RetryEventHandler._handle(event)

        assert attempt_count == 2
        mock_sleep.assert_called_once()


@pytest.fixture(params=[False, True], ids=["outbox-off", "outbox-on"])
def outbox(request, test_domain):
    if request.param:
        test_domain.config["enable_outbox"] = True
        test_domain.config["server"]["default_subscription_type"] = "stream"
        test_domain.init(traverse=False)
    return request.param


class TestCommitFailureRetry:
    """Only a version conflict at commit is retried. Any other failure at
    commit surfaces after one run of the handler."""

    @patch("protean.utils.mixins.time.sleep")
    def test_value_error_at_commit_is_not_retried(
        self, mock_sleep, test_domain, outbox
    ):
        attempt_count = 0

        class RegisteringHandler(BaseCommandHandler):
            @handle(RenameUser)
            def rename(self, command: RenameUser) -> None:
                nonlocal attempt_count
                attempt_count += 1
                user = User.register(
                    user_id=command.user_id, name=command.name, email="j@example.com"
                )
                current_domain.repository_for(User).add(user)

        test_domain.register(RegisteringHandler, part_of=User)
        test_domain.init(traverse=False)
        assert test_domain.has_outbox is outbox

        command = RenameUser(user_id=str(uuid4()), name="Jane")
        enriched = test_domain._enrich_command(command, True)
        with patch.object(
            test_domain.event_store.store, "append", side_effect=ValueError("boom")
        ):
            with pytest.raises(TransactionError) as exc_info:
                RegisteringHandler._handle(enriched)

        assert exc_info.value.extra_info["original_exception"] == "ValueError"
        assert exc_info.value.extra_info["original_message"] == "boom"
        assert isinstance(exc_info.value.__cause__, ValueError)
        assert attempt_count == 1
        mock_sleep.assert_not_called()

    @patch("protean.utils.mixins.time.sleep")
    def test_event_store_conflict_at_commit_is_retried(
        self, mock_sleep, test_domain, outbox, caplog
    ):
        attempt_count = 0
        stale = None

        class StaleHandler(BaseCommandHandler):
            @handle(RenameUser)
            def rename(self, command: RenameUser) -> None:
                nonlocal attempt_count
                attempt_count += 1
                repo = current_domain.repository_for(User)
                # The first attempt writes the copy loaded before the winner
                # committed, so its append hits a real version conflict.
                if attempt_count == 1:
                    assert stale is not None
                    user = stale
                else:
                    user = repo.get(command.user_id)
                user.change_name(command.name)
                repo.add(user)

        test_domain.register(StaleHandler, part_of=User)
        test_domain.init(traverse=False)
        assert test_domain.has_outbox is outbox

        identifier = _create_user(test_domain)
        stale = test_domain.repository_for(User).get(identifier)
        with UnitOfWork():
            winner = test_domain.repository_for(User).get(identifier)
            winner.change_name("Winner")
            test_domain.repository_for(User).add(winner)

        command = RenameUser(user_id=identifier, name="Jane")
        enriched = test_domain._enrich_command(command, True)
        with caplog.at_level(logging.ERROR, logger="protean.core.unit_of_work"):
            StaleHandler._handle(enriched)

        assert attempt_count == 2
        mock_sleep.assert_called_once()
        failed = [r for r in caplog.records if r.getMessage() == "uow.commit_failed"]
        assert len(failed) == 1
        assert failed[0].exc_info is not None
        assert failed[0].exc_info[0] is ExpectedVersionError
        assert test_domain.repository_for(User).get(identifier).name == "Jane"


class TestSyncEventHandlerConflict:
    """A version conflict raised by a sync event handler does not rerun the command.

    Under sync processing the event handlers run inside the command's commit,
    after its writes are saved. Rerunning the command would save them again.
    """

    @staticmethod
    def _registering_handler(runs: list[str]) -> type[BaseCommandHandler]:
        class RegisteringHandler(BaseCommandHandler):
            @handle(RenameUser)
            def rename(self, command: RenameUser) -> None:
                runs.append(command.user_id)
                user = User.register(
                    user_id=command.user_id, name=command.name, email="j@example.com"
                )
                current_domain.repository_for(User).add(user)

        return RegisteringHandler

    @staticmethod
    def _stored_types(test_domain, user_id: str) -> list[str]:
        messages = test_domain.event_store.store.read(f"test::user-{user_id}")
        return [m.metadata.headers.type for m in messages]

    @patch("protean.utils.mixins.time.sleep")
    def test_conflict_from_sync_event_handler_is_not_retried(
        self, mock_sleep, test_domain, caplog
    ):
        runs: list[str] = []
        handler_runs = 0
        RegisteringHandler = self._registering_handler(runs)

        class ConflictingReaction(BaseEventHandler):
            @handle(UserRegistered)
            def on_registered(self, event: UserRegistered) -> None:
                nonlocal handler_runs
                handler_runs += 1
                raise ExpectedVersionError("reaction conflicted")

        test_domain.register(RegisteringHandler, part_of=User)
        test_domain.register(ConflictingReaction, part_of=User)
        test_domain.init(traverse=False)
        assert test_domain.config["event_processing"] == "sync"

        user_id = str(uuid4())
        enriched = test_domain._enrich_command(
            RenameUser(user_id=user_id, name="Jane"), True
        )
        with (
            caplog.at_level(logging.ERROR, logger="protean.core.unit_of_work"),
            pytest.raises(TransactionError) as exc_info,
        ):
            RegisteringHandler._handle(enriched)

        cause = exc_info.value.__cause__
        assert isinstance(cause, ExpectedVersionError)
        assert str(cause) == "reaction conflicted"
        failed = [r for r in caplog.records if r.getMessage() == "uow.commit_failed"]
        assert len(failed) == 1
        assert failed[0].exc_info is not None
        assert failed[0].exc_info[0] is ExpectedVersionError
        assert exc_info.value.extra_info["original_exception"] == (
            "ExpectedVersionError"
        )
        assert runs == [user_id]
        # The reaction's own @handle wrapper retried it, the command did not.
        assert handler_runs == 1 + _VERSION_RETRY_DEFAULTS["max_retries"]
        assert self._stored_types(test_domain, user_id) == ["Test.UserRegistered.v1"]
        assert test_domain.repository_for(User).get(user_id).name == "Jane"

    @patch("protean.utils.mixins.time.sleep")
    def test_conflict_from_sync_event_handler_through_process(
        self, mock_sleep, test_domain
    ):
        runs: list[str] = []
        RegisteringHandler = self._registering_handler(runs)

        class ConflictingReaction(BaseEventHandler):
            @handle(UserRegistered)
            def on_registered(self, event: UserRegistered) -> None:
                raise ExpectedVersionError("reaction conflicted")

        test_domain.register(RegisteringHandler, part_of=User)
        test_domain.register(ConflictingReaction, part_of=User)
        test_domain.init(traverse=False)

        user_id = str(uuid4())
        with pytest.raises(TransactionError) as exc_info:
            test_domain.process(
                RenameUser(user_id=user_id, name="Jane"), asynchronous=False
            )

        assert isinstance(exc_info.value.__cause__, ExpectedVersionError)
        assert runs == [user_id]
        assert self._stored_types(test_domain, user_id) == ["Test.UserRegistered.v1"]

    @patch("protean.utils.mixins.time.sleep")
    def test_other_handler_classes_run_after_a_conflict(self, mock_sleep, test_domain):
        runs: list[str] = []
        ran: list[str] = []
        RegisteringHandler = self._registering_handler(runs)

        class ConflictingReaction(BaseEventHandler):
            @handle(UserRegistered)
            def on_registered(self, event: UserRegistered) -> None:
                raise ExpectedVersionError("reaction conflicted")

        class RecordingReaction(BaseEventHandler):
            @handle(UserRegistered)
            def on_registered(self, event: UserRegistered) -> None:
                ran.append(event.user_id)

        test_domain.register(RegisteringHandler, part_of=User)
        test_domain.register(ConflictingReaction, part_of=User)
        test_domain.register(RecordingReaction, part_of=User)
        test_domain.init(traverse=False)

        user_id = str(uuid4())
        enriched = test_domain._enrich_command(
            RenameUser(user_id=user_id, name="Jane"), True
        )
        with pytest.raises(TransactionError) as exc_info:
            RegisteringHandler._handle(enriched)

        assert isinstance(exc_info.value.__cause__, ExpectedVersionError)
        assert ran == [user_id]
        assert runs == [user_id]

    @patch("protean.utils.mixins.time.sleep")
    def test_conflict_and_another_failure_are_grouped(self, mock_sleep, test_domain):
        runs: list[str] = []
        RegisteringHandler = self._registering_handler(runs)

        class ConflictingReaction(BaseEventHandler):
            @handle(UserRegistered)
            def on_registered(self, event: UserRegistered) -> None:
                raise ExpectedVersionError("reaction conflicted")

        class FailingReaction(BaseEventHandler):
            @handle(UserRegistered)
            def on_registered(self, event: UserRegistered) -> None:
                raise ValueError("reaction failed")

        test_domain.register(RegisteringHandler, part_of=User)
        test_domain.register(ConflictingReaction, part_of=User)
        test_domain.register(FailingReaction, part_of=User)
        test_domain.init(traverse=False)

        user_id = str(uuid4())
        enriched = test_domain._enrich_command(
            RenameUser(user_id=user_id, name="Jane"), True
        )
        with pytest.raises(TransactionError) as exc_info:
            RegisteringHandler._handle(enriched)

        cause = exc_info.value.__cause__
        assert isinstance(cause, ExceptionGroup)
        assert sorted(type(e).__name__ for e in cause.exceptions) == [
            "ExpectedVersionError",
            "ValueError",
        ]
        assert runs == [user_id]

    @pytest.mark.parametrize(
        "make_error",
        [
            # Named like SQLAlchemy's, which the commit translates to a
            # version conflict when the commit's own write raises it.
            lambda: type("StaleDataError", (Exception,), {})("stale in reaction"),
            lambda: ConfigurationError("reaction misconfigured"),
            # Under sync processing the event handler runs inside the commit,
            # after the events are durable. Retrying would append them again.
            lambda: ValueError("reaction failed"),
        ],
        ids=["stale-data-error", "configuration-error", "value-error"],
    )
    def test_any_reaction_failure_is_wrapped_and_not_retried(
        self, test_domain, make_error
    ):
        runs: list[str] = []
        RegisteringHandler = self._registering_handler(runs)
        error = make_error()

        class FailingReaction(BaseEventHandler):
            @handle(UserRegistered)
            def on_registered(self, event: UserRegistered) -> None:
                raise error

        test_domain.register(RegisteringHandler, part_of=User)
        test_domain.register(FailingReaction, part_of=User)
        test_domain.init(traverse=False)

        user_id = str(uuid4())
        enriched = test_domain._enrich_command(
            RenameUser(user_id=user_id, name="Jane"), True
        )
        with pytest.raises(TransactionError) as exc_info:
            RegisteringHandler._handle(enriched)

        assert exc_info.value.__cause__ is error
        assert exc_info.value.extra_info["original_exception"] == (type(error).__name__)
        assert runs == [user_id]
        assert self._stored_types(test_domain, user_id) == ["Test.UserRegistered.v1"]

    def test_a_reaction_failure_with_a_broken_str_keeps_its_cause(self, test_domain):
        runs: list[str] = []
        RegisteringHandler = self._registering_handler(runs)

        class Unprintable(Exception):
            def __str__(self) -> str:
                raise RuntimeError("str is broken")

        error = Unprintable()

        class FailingReaction(BaseEventHandler):
            @handle(UserRegistered)
            def on_registered(self, event: UserRegistered) -> None:
                raise error

        test_domain.register(RegisteringHandler, part_of=User)
        test_domain.register(FailingReaction, part_of=User)
        test_domain.init(traverse=False)

        user_id = str(uuid4())
        enriched = test_domain._enrich_command(
            RenameUser(user_id=user_id, name="Jane"), True
        )
        with pytest.raises(TransactionError) as exc_info:
            RegisteringHandler._handle(enriched)

        assert exc_info.value.__cause__ is error
        assert exc_info.value.extra_info["original_exception"] == "Unprintable"
        assert exc_info.value.extra_info["original_message"] == "<unprintable>"
        assert runs == [user_id]

    @patch("protean.utils.mixins.time.sleep")
    def test_handler_own_write_conflict_is_retried_by_the_handler(
        self, mock_sleep, test_domain
    ):
        runs: list[str] = []
        attempts = 0
        stale = None
        RegisteringHandler = self._registering_handler(runs)

        class RenamingReaction(BaseEventHandler):
            @handle(UserRegistered)
            def on_registered(self, event: UserRegistered) -> None:
                nonlocal attempts
                if stale is None or event.user_id == stale.user_id:
                    return  # setup registers the other user; ignore it
                attempts += 1
                repo = current_domain.repository_for(User)
                # The first attempt writes a copy loaded before another write
                # committed, so its own commit hits a real version conflict.
                if attempts == 1:
                    other = stale
                else:
                    other = repo.get(stale.user_id)
                other.change_name("Reacted")
                repo.add(other)

        test_domain.register(RegisteringHandler, part_of=User)
        test_domain.register(RenamingReaction, part_of=User)
        test_domain.init(traverse=False)

        other_id = _create_user(test_domain)
        stale = test_domain.repository_for(User).get(other_id)
        with UnitOfWork():
            winner = test_domain.repository_for(User).get(other_id)
            winner.change_name("Winner")
            test_domain.repository_for(User).add(winner)

        user_id = str(uuid4())
        enriched = test_domain._enrich_command(
            RenameUser(user_id=user_id, name="Jane"), True
        )
        RegisteringHandler._handle(enriched)

        assert runs == [user_id]
        assert attempts == 2
        assert test_domain.repository_for(User).get(other_id).name == "Reacted"
        assert self._stored_types(test_domain, user_id) == ["Test.UserRegistered.v1"]


# ---------------------------------------------------------------------------
# Nested handlers: retry happens at the outermost handler only
# ---------------------------------------------------------------------------


class Account(BaseAggregate):
    name: String(max_length=50)


class OpenAccount(BaseCommand):
    account_id: Identifier(required=True)


class WriteAccount(BaseCommand):
    account_id: Identifier(required=True)


class TestNestedHandlerRetry:
    """A handler that runs inside an active UnitOfWork does not retry in place.

    Its UnitOfWork joins the outer one, so a failed attempt has already marked
    the whole transaction rollback-only. The conflict propagates, and the
    outermost handler retries the whole chain in a fresh UnitOfWork.
    """

    @pytest.fixture(autouse=True)
    def register_accounts(self, test_domain):
        test_domain.register(Account)
        test_domain.register(OpenAccount, part_of=Account)
        test_domain.register(WriteAccount, part_of=Account)

    @patch("protean.utils.mixins.time.sleep")
    def test_conflict_in_nested_handler_is_retried_by_the_outer_handler(
        self, mock_sleep, test_domain
    ):
        outer_runs = 0
        inner_runs = 0

        class AccountHandlers(BaseCommandHandler):
            @handle(OpenAccount)
            def open(self, command: OpenAccount) -> None:
                nonlocal outer_runs
                outer_runs += 1
                current_domain.process(
                    WriteAccount(account_id=command.account_id), asynchronous=False
                )

            @handle(WriteAccount)
            def write(self, command: WriteAccount) -> None:
                nonlocal inner_runs
                inner_runs += 1
                if inner_runs == 1:
                    raise ExpectedVersionError("stale")
                current_domain.repository_for(Account).add(
                    Account(id=command.account_id, name="written")
                )

        test_domain.register(AccountHandlers, part_of=Account)
        test_domain.init(traverse=False)

        test_domain.process(OpenAccount(account_id="a1"), asynchronous=False)

        assert inner_runs == 2
        assert outer_runs == 2
        account = test_domain.repository_for(Account).get_or_none("a1")
        assert account is not None
        assert account.name == "written"
        mock_sleep.assert_called_once()

    @patch("protean.utils.mixins.time.sleep")
    def test_handler_inside_an_open_unit_of_work_does_not_retry(
        self, mock_sleep, test_domain
    ):
        runs = 0

        class AccountHandlers(BaseCommandHandler):
            @handle(WriteAccount)
            def write(self, command: WriteAccount) -> None:
                nonlocal runs
                runs += 1
                raise ExpectedVersionError("stale")

        test_domain.register(AccountHandlers, part_of=Account)
        test_domain.init(traverse=False)

        with pytest.raises(ExpectedVersionError):
            with UnitOfWork():
                test_domain.process(WriteAccount(account_id="a1"), asynchronous=False)

        assert runs == 1
        mock_sleep.assert_not_called()

    @patch("protean.utils.mixins.time.sleep")
    def test_a_nested_conflict_that_never_clears_is_retried_only_by_the_outer_handler(
        self, mock_sleep, test_domain
    ):
        outer_runs = 0
        inner_runs = 0

        class AccountHandlers(BaseCommandHandler):
            @handle(OpenAccount)
            def open(self, command: OpenAccount) -> None:
                nonlocal outer_runs
                outer_runs += 1
                current_domain.process(
                    WriteAccount(account_id=command.account_id), asynchronous=False
                )

            @handle(WriteAccount)
            def write(self, command: WriteAccount) -> None:
                nonlocal inner_runs
                inner_runs += 1
                raise ExpectedVersionError("stale")

        test_domain.register(AccountHandlers, part_of=Account)
        test_domain.init(traverse=False)

        with pytest.raises(ExpectedVersionError):
            test_domain.process(OpenAccount(account_id="a1"), asynchronous=False)

        max_retries = _VERSION_RETRY_DEFAULTS["max_retries"]
        assert outer_runs == max_retries + 1
        assert inner_runs == max_retries + 1
        assert mock_sleep.call_count == max_retries


class CloseAccount(BaseCommand):
    account_id: Identifier(required=True)


class TestThreeLevelNestedRetry:
    @pytest.fixture(autouse=True)
    def register_accounts(self, test_domain):
        test_domain.register(Account)
        test_domain.register(OpenAccount, part_of=Account)
        test_domain.register(WriteAccount, part_of=Account)
        test_domain.register(CloseAccount, part_of=Account)

    def _register_chain(self, test_domain, runs, conflicts):
        class AccountHandlers(BaseCommandHandler):
            @handle(CloseAccount)
            def first(self, command: CloseAccount) -> None:
                runs["first"] += 1
                current_domain.process(
                    OpenAccount(account_id=command.account_id), asynchronous=False
                )

            @handle(OpenAccount)
            def second(self, command: OpenAccount) -> None:
                runs["second"] += 1
                current_domain.process(
                    WriteAccount(account_id=command.account_id), asynchronous=False
                )

            @handle(WriteAccount)
            def third(self, command: WriteAccount) -> None:
                runs["third"] += 1
                if runs["third"] <= conflicts:
                    raise ExpectedVersionError("stale")
                current_domain.repository_for(Account).add(
                    Account(id=command.account_id, name="written")
                )

        test_domain.register(AccountHandlers, part_of=Account)
        test_domain.init(traverse=False)

    @patch("protean.utils.mixins.time.sleep")
    def test_a_conflict_two_levels_down_is_retried_by_the_outermost_handler(
        self, mock_sleep, test_domain
    ):
        runs = {"first": 0, "second": 0, "third": 0}
        self._register_chain(test_domain, runs, conflicts=1)

        test_domain.process(CloseAccount(account_id="a1"), asynchronous=False)

        assert runs == {"first": 2, "second": 2, "third": 2}
        account = test_domain.repository_for(Account).get_or_none("a1")
        assert account is not None
        assert account.name == "written"
        mock_sleep.assert_called_once()

    @patch("protean.utils.mixins.time.sleep")
    def test_retries_are_not_multiplied_across_levels(self, mock_sleep, test_domain):
        runs = {"first": 0, "second": 0, "third": 0}
        self._register_chain(test_domain, runs, conflicts=1_000)

        with pytest.raises(ExpectedVersionError):
            test_domain.process(CloseAccount(account_id="a1"), asynchronous=False)

        attempts = _VERSION_RETRY_DEFAULTS["max_retries"] + 1
        assert runs == {"first": attempts, "second": attempts, "third": attempts}


class Wallet(BaseAggregate):
    owner: String(max_length=50)


class WalletOpened(BaseEvent):
    wallet_id: Identifier(required=True)


class OpenWallet(BaseCommand):
    wallet_id: Identifier(required=True)


class FundWallet(BaseCommand):
    wallet_id: Identifier(required=True)


class TestNestedRetryOutboxRows:
    """Outbox rows a nested handler writes belong to the outer transaction.

    A failed outer attempt rolls them back with everything else, and the
    retry that succeeds writes them once.
    """

    @pytest.fixture(autouse=True)
    def register_wallets(self, test_domain):
        test_domain.config["enable_outbox"] = True
        test_domain.config["server"]["default_subscription_type"] = "stream"
        test_domain.register(Wallet)
        test_domain.register(WalletOpened, part_of=Wallet)
        test_domain.register(OpenWallet, part_of=Wallet)
        test_domain.register(FundWallet, part_of=Wallet)

    def _register_chain(self, test_domain, runs, fail_inner, fail_outer):
        class WalletHandlers(BaseCommandHandler):
            @handle(OpenWallet)
            def open(self, command: OpenWallet) -> None:
                runs["outer"] += 1
                current_domain.process(
                    FundWallet(wallet_id=command.wallet_id), asynchronous=False
                )
                if runs["outer"] <= fail_outer:
                    raise ExpectedVersionError("stale")

            @handle(FundWallet)
            def fund(self, command: FundWallet) -> None:
                runs["inner"] += 1
                if runs["inner"] <= fail_inner:
                    raise ExpectedVersionError("stale")
                wallet = Wallet(id=command.wallet_id, owner="o")
                wallet.raise_(WalletOpened(wallet_id=wallet.id))
                current_domain.repository_for(Wallet).add(wallet)

        test_domain.register(WalletHandlers, part_of=Wallet)
        test_domain.init(traverse=False)

    def _outbox_types(self, test_domain) -> list[str]:
        rows = test_domain._get_outbox_repo("default").find_unprocessed()
        return [row.type for row in rows]

    @pytest.mark.parametrize(
        "fail_inner, fail_outer",
        [(1, 0), (0, 1)],
        ids=["conflict_in_nested_handler", "conflict_after_nested_handler"],
    )
    @patch("protean.utils.mixins.time.sleep")
    def test_outer_retry_writes_the_nested_outbox_row_once(
        self, mock_sleep, test_domain, fail_inner, fail_outer
    ):
        runs = {"outer": 0, "inner": 0}
        self._register_chain(test_domain, runs, fail_inner, fail_outer)

        test_domain.process(OpenWallet(wallet_id="w1"), asynchronous=False)

        assert runs["outer"] == 2
        assert self._outbox_types(test_domain) == [WalletOpened.__type__]

    @patch("protean.utils.mixins.time.sleep")
    def test_a_failed_outer_transaction_leaves_no_nested_outbox_row(
        self, mock_sleep, test_domain
    ):
        runs = {"outer": 0, "inner": 0}
        self._register_chain(test_domain, runs, fail_inner=0, fail_outer=1_000)

        with pytest.raises(ExpectedVersionError):
            test_domain.process(OpenWallet(wallet_id="w1"), asynchronous=False)

        assert runs["inner"] == _VERSION_RETRY_DEFAULTS["max_retries"] + 1
        assert self._outbox_types(test_domain) == []
        assert test_domain.repository_for(Wallet).get_or_none("w1") is None
