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
from protean.exceptions import ExpectedVersionError
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

    def test_config_from_active_domain(self, test_domain):
        """Config is read from the active domain when available."""
        config = _get_version_retry_config()
        assert config["enabled"] is True
        assert config["max_retries"] == 3
        assert config["base_delay_seconds"] == 0.05
        assert config["max_delay_seconds"] == 1.0

    def test_config_custom_overrides(self, test_domain):
        """Custom config values are respected."""
        test_domain.config["server"]["version_retry"] = {
            "enabled": False,
            "max_retries": 5,
            "base_delay_seconds": 0.1,
            "max_delay_seconds": 2.0,
        }
        config = _get_version_retry_config()
        assert config["enabled"] is False
        assert config["max_retries"] == 5
        assert config["base_delay_seconds"] == 0.1
        assert config["max_delay_seconds"] == 2.0

    def test_config_partial_overrides(self, test_domain):
        """Partial config falls back to defaults for missing keys."""
        test_domain.config["server"]["version_retry"] = {"max_retries": 10}
        config = _get_version_retry_config()
        assert config["enabled"] is True  # default
        assert config["max_retries"] == 10  # overridden
        assert config["base_delay_seconds"] == 0.05  # default

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

    def test_valid_config_logs_no_warning(self, test_domain, caplog):
        caplog.set_level(logging.WARNING, logger="protean.utils.mixins")

        _get_version_retry_config()

        assert [r for r in caplog.records if r.name == "protean.utils.mixins"] == []

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
    def test_succeeds_on_first_attempt(self, mock_sleep, test_domain):
        """No retry needed when handler succeeds immediately."""
        test_domain.register(UserCommandHandler, part_of=User)
        test_domain.init(traverse=False)

        identifier = _create_user(test_domain)

        command = RenameUser(user_id=identifier, name="Jane")
        enriched = test_domain._enrich_command(command, True)
        UserCommandHandler._handle(enriched)

        # Verify the rename happened
        repo = test_domain.repository_for(User)
        user = repo.get(identifier)
        assert user.name == "Jane"
        mock_sleep.assert_not_called()

    @patch("protean.utils.mixins.time.sleep")
    def test_retries_on_version_error_then_succeeds(self, mock_sleep, test_domain):
        """Handler retries and succeeds after transient version conflict."""
        attempt_count = 0

        class RetryTestHandler(BaseCommandHandler):
            @handle(RenameUser)
            def rename(self, command: RenameUser) -> None:
                nonlocal attempt_count
                attempt_count += 1
                if attempt_count == 1:
                    raise ExpectedVersionError(
                        "Wrong expected version: 0 (Stream: test, Stream Version: 1)"
                    )
                repo = current_domain.repository_for(User)
                user = repo.get(command.user_id)
                user.change_name(command.name)
                repo.add(user)

        test_domain.register(RetryTestHandler, part_of=User)
        test_domain.init(traverse=False)

        identifier = _create_user(test_domain)

        command = RenameUser(user_id=identifier, name="Jane")
        enriched = test_domain._enrich_command(command, True)
        RetryTestHandler._handle(enriched)

        assert attempt_count == 2
        mock_sleep.assert_called_once()

    @patch("protean.utils.mixins.time.sleep")
    def test_retries_twice_then_succeeds(self, mock_sleep, test_domain):
        """Handler succeeds on third attempt after two version conflicts."""
        attempt_count = 0

        class RetryTwiceHandler(BaseCommandHandler):
            @handle(RenameUser)
            def rename(self, command: RenameUser) -> None:
                nonlocal attempt_count
                attempt_count += 1
                if attempt_count <= 2:
                    raise ExpectedVersionError("version conflict")
                repo = current_domain.repository_for(User)
                user = repo.get(command.user_id)
                user.change_name(command.name)
                repo.add(user)

        test_domain.register(RetryTwiceHandler, part_of=User)
        test_domain.init(traverse=False)

        identifier = _create_user(test_domain)

        command = RenameUser(user_id=identifier, name="Jane")
        enriched = test_domain._enrich_command(command, True)
        RetryTwiceHandler._handle(enriched)

        assert attempt_count == 3
        assert mock_sleep.call_count == 2

    @patch("protean.utils.mixins.time.sleep")
    def test_exhausts_retries_and_raises(self, mock_sleep, test_domain):
        """Raises ExpectedVersionError after exhausting all retries."""

        class AlwaysFailHandler(BaseCommandHandler):
            @handle(RenameUser)
            def rename(self, command: RenameUser) -> None:
                raise ExpectedVersionError("persistent version conflict")

        test_domain.register(AlwaysFailHandler, part_of=User)
        test_domain.init(traverse=False)

        identifier = _create_user(test_domain)

        command = RenameUser(user_id=identifier, name="Jane")
        enriched = test_domain._enrich_command(command, True)

        with pytest.raises(ExpectedVersionError, match="persistent version conflict"):
            AlwaysFailHandler._handle(enriched)

        # Default: 3 retries = 4 total attempts, 3 sleeps
        assert mock_sleep.call_count == 3

    def test_non_version_error_propagates_immediately(self, test_domain):
        """Non-ExpectedVersionError exceptions propagate without retrying."""
        attempt_count = 0

        class BadHandler(BaseCommandHandler):
            @handle(RenameUser)
            def rename(self, command: RenameUser) -> None:
                nonlocal attempt_count
                attempt_count += 1
                raise ValueError("business rule violation")

        test_domain.register(BadHandler, part_of=User)
        test_domain.init(traverse=False)

        identifier = _create_user(test_domain)

        command = RenameUser(user_id=identifier, name="Jane")
        enriched = test_domain._enrich_command(command, True)

        with pytest.raises(ValueError, match="business rule violation"):
            BadHandler._handle(enriched)

        assert attempt_count == 1  # No retry


# ---------------------------------------------------------------------------
# Disabled retry tests
# ---------------------------------------------------------------------------


class TestRetryDisabled:
    """Test that retry can be disabled via configuration."""

    @patch("protean.utils.mixins.time.sleep")
    def test_disabled_via_enabled_flag(self, mock_sleep, test_domain):
        """Setting enabled=False bypasses retry entirely."""

        class FailHandler(BaseCommandHandler):
            @handle(RenameUser)
            def rename(self, command: RenameUser) -> None:
                raise ExpectedVersionError("conflict")

        test_domain.register(FailHandler, part_of=User)
        test_domain.init(traverse=False)

        # Set config AFTER init to avoid any reset
        test_domain.config["server"]["version_retry"]["enabled"] = False

        identifier = _create_user(test_domain)

        command = RenameUser(user_id=identifier, name="Jane")
        enriched = test_domain._enrich_command(command, True)

        with pytest.raises(ExpectedVersionError):
            FailHandler._handle(enriched)

        mock_sleep.assert_not_called()

    @patch("protean.utils.mixins.time.sleep")
    def test_disabled_via_zero_retries(self, mock_sleep, test_domain):
        """Setting max_retries=0 bypasses retry."""

        class FailHandler(BaseCommandHandler):
            @handle(RenameUser)
            def rename(self, command: RenameUser) -> None:
                raise ExpectedVersionError("conflict")

        test_domain.register(FailHandler, part_of=User)
        test_domain.init(traverse=False)

        # Set config AFTER init
        test_domain.config["server"]["version_retry"]["max_retries"] = 0

        identifier = _create_user(test_domain)

        command = RenameUser(user_id=identifier, name="Jane")
        enriched = test_domain._enrich_command(command, True)

        with pytest.raises(ExpectedVersionError):
            FailHandler._handle(enriched)

        mock_sleep.assert_not_called()


# ---------------------------------------------------------------------------
# Backoff timing tests
# ---------------------------------------------------------------------------


class TestExponentialBackoff:
    """Verify exponential backoff delays and capping."""

    @patch("protean.utils.mixins.time.sleep")
    def test_exponential_backoff_delays(self, mock_sleep, test_domain):
        """Delays follow 2^attempt * base_delay pattern."""
        attempt_count = 0

        class FailHandler(BaseCommandHandler):
            @handle(RenameUser)
            def rename(self, command: RenameUser) -> None:
                nonlocal attempt_count
                attempt_count += 1
                raise ExpectedVersionError("conflict")

        test_domain.register(FailHandler, part_of=User)
        test_domain.init(traverse=False)

        # Set config AFTER init
        test_domain.config["server"]["version_retry"]["max_retries"] = 4
        test_domain.config["server"]["version_retry"]["base_delay_seconds"] = 0.1
        test_domain.config["server"]["version_retry"]["max_delay_seconds"] = 10.0

        identifier = _create_user(test_domain)

        command = RenameUser(user_id=identifier, name="Jane")
        enriched = test_domain._enrich_command(command, True)

        with pytest.raises(ExpectedVersionError):
            FailHandler._handle(enriched)

        assert attempt_count == 5  # initial + 4 retries
        delays = [call.args[0] for call in mock_sleep.call_args_list]
        # base=0.1: 0.1, 0.2, 0.4, 0.8
        assert delays == pytest.approx([0.1, 0.2, 0.4, 0.8])

    @patch("protean.utils.mixins.time.sleep")
    def test_delay_capped_at_max(self, mock_sleep, test_domain):
        """Backoff delay never exceeds max_delay_seconds."""

        class FailHandler(BaseCommandHandler):
            @handle(RenameUser)
            def rename(self, command: RenameUser) -> None:
                raise ExpectedVersionError("conflict")

        test_domain.register(FailHandler, part_of=User)
        test_domain.init(traverse=False)

        # Set config AFTER init
        test_domain.config["server"]["version_retry"]["max_retries"] = 5
        test_domain.config["server"]["version_retry"]["base_delay_seconds"] = 0.5
        test_domain.config["server"]["version_retry"]["max_delay_seconds"] = 1.0

        identifier = _create_user(test_domain)

        command = RenameUser(user_id=identifier, name="Jane")
        enriched = test_domain._enrich_command(command, True)

        with pytest.raises(ExpectedVersionError):
            FailHandler._handle(enriched)

        delays = [call.args[0] for call in mock_sleep.call_args_list]
        # base=0.5: 0.5, 1.0, 1.0, 1.0, 1.0 (capped at 1.0)
        assert delays == pytest.approx([0.5, 1.0, 1.0, 1.0, 1.0])
        assert all(d <= 1.0 for d in delays)


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


# ---------------------------------------------------------------------------
# Integration with real version conflicts
# ---------------------------------------------------------------------------


class TestRealVersionConflict:
    """Test retry with actual version conflicts from event-sourced aggregates."""

    @patch("protean.utils.mixins.time.sleep")
    def test_concurrent_modification_retries(self, mock_sleep, test_domain):
        """When a handler hits a version conflict, the retry resolves it
        by re-executing with a fresh UoW."""
        attempt_count = 0

        class ConflictHandler(BaseCommandHandler):
            @handle(RenameUser)
            def rename(self, command: RenameUser) -> None:
                nonlocal attempt_count
                attempt_count += 1
                if attempt_count == 1:
                    # Simulate a version conflict on first attempt
                    raise ExpectedVersionError(
                        "Wrong expected version: 0 (Stream: test, Stream Version: 1)"
                    )
                # On retry, succeed
                repo = current_domain.repository_for(User)
                user = repo.get(command.user_id)
                user.change_name(command.name)
                repo.add(user)

        test_domain.register(ConflictHandler, part_of=User)
        test_domain.init(traverse=False)

        identifier = _create_user(test_domain)

        command = RenameUser(user_id=identifier, name="Jane")
        enriched = test_domain._enrich_command(command, True)
        ConflictHandler._handle(enriched)

        assert attempt_count == 2
        mock_sleep.assert_called_once()

        # Verify final state
        repo = test_domain.repository_for(User)
        user = repo.get(identifier)
        assert user.name == "Jane"


# ---------------------------------------------------------------------------
# Logging tests
# ---------------------------------------------------------------------------


class TestRetryLogging:
    """Verify debug logging on retry attempts."""

    @patch("protean.utils.mixins.time.sleep")
    def test_debug_log_on_retry(self, mock_sleep, test_domain, caplog):
        """Debug log emitted for each retry attempt."""
        import logging

        attempt_count = 0

        class LogHandler(BaseCommandHandler):
            @handle(RenameUser)
            def rename(self, command: RenameUser) -> None:
                nonlocal attempt_count
                attempt_count += 1
                if attempt_count <= 2:
                    raise ExpectedVersionError("version mismatch")

        test_domain.register(LogHandler, part_of=User)
        test_domain.init(traverse=False)

        identifier = _create_user(test_domain)

        command = RenameUser(user_id=identifier, name="Jane")
        enriched = test_domain._enrich_command(command, True)

        with caplog.at_level(logging.DEBUG, logger="protean.utils.mixins"):
            LogHandler._handle(enriched)

        retry_logs = [r for r in caplog.records if "Version conflict" in r.message]
        assert len(retry_logs) == 2
        assert "retrying (1/3)" in retry_logs[0].message
        assert "retrying (2/3)" in retry_logs[1].message

    @patch("protean.utils.mixins.time.sleep")
    def test_no_log_on_success(self, mock_sleep, test_domain, caplog):
        """No retry logs when handler succeeds on first attempt."""
        import logging

        class SuccessHandler(BaseCommandHandler):
            @handle(RenameUser)
            def rename(self, command: RenameUser) -> None:
                pass  # succeeds immediately

        test_domain.register(SuccessHandler, part_of=User)
        test_domain.init(traverse=False)

        identifier = _create_user(test_domain)

        command = RenameUser(user_id=identifier, name="Jane")
        enriched = test_domain._enrich_command(command, True)

        with caplog.at_level(logging.DEBUG, logger="protean.utils.mixins"):
            SuccessHandler._handle(enriched)

        retry_logs = [r for r in caplog.records if "Version conflict" in r.message]
        assert len(retry_logs) == 0
        mock_sleep.assert_not_called()


# ---------------------------------------------------------------------------
# Handler return value tests
# ---------------------------------------------------------------------------


class TestHandlerReturnValue:
    """Verify that return values pass through the retry wrapper correctly."""

    @patch("protean.utils.mixins.time.sleep")
    def test_return_value_preserved_on_retry(self, mock_sleep, test_domain):
        """Command handler return value is preserved even after retries."""
        attempt_count = 0

        class ReturningHandler(BaseCommandHandler):
            @handle(RenameUser)
            def rename(self, command: RenameUser) -> None:
                nonlocal attempt_count
                attempt_count += 1
                if attempt_count == 1:
                    raise ExpectedVersionError("conflict")

        test_domain.register(ReturningHandler, part_of=User)
        test_domain.init(traverse=False)

        identifier = _create_user(test_domain)

        command = RenameUser(user_id=identifier, name="Jane")
        enriched = test_domain._enrich_command(command, True)
        result = ReturningHandler._handle(enriched)

        assert result is None
        assert attempt_count == 2


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Edge cases and boundary conditions for version retry."""

    @patch("protean.utils.mixins.time.sleep")
    def test_max_retries_one(self, mock_sleep, test_domain):
        """With max_retries=1, only one retry is attempted."""
        attempt_count = 0

        class OneRetryHandler(BaseCommandHandler):
            @handle(RenameUser)
            def rename(self, command: RenameUser) -> None:
                nonlocal attempt_count
                attempt_count += 1
                raise ExpectedVersionError("conflict")

        test_domain.register(OneRetryHandler, part_of=User)
        test_domain.init(traverse=False)

        # Set config AFTER init
        test_domain.config["server"]["version_retry"]["max_retries"] = 1

        identifier = _create_user(test_domain)

        command = RenameUser(user_id=identifier, name="Jane")
        enriched = test_domain._enrich_command(command, True)

        with pytest.raises(ExpectedVersionError):
            OneRetryHandler._handle(enriched)

        assert attempt_count == 2  # initial + 1 retry
        assert mock_sleep.call_count == 1

    @patch("protean.utils.mixins.time.sleep")
    def test_handler_raises_different_error_after_version_error(
        self, mock_sleep, test_domain
    ):
        """If handler raises a different error on retry, it propagates."""
        attempt_count = 0

        class MixedErrorHandler(BaseCommandHandler):
            @handle(RenameUser)
            def rename(self, command: RenameUser) -> None:
                nonlocal attempt_count
                attempt_count += 1
                if attempt_count == 1:
                    raise ExpectedVersionError("conflict")
                raise RuntimeError("unexpected error on retry")

        test_domain.register(MixedErrorHandler, part_of=User)
        test_domain.init(traverse=False)

        identifier = _create_user(test_domain)

        command = RenameUser(user_id=identifier, name="Jane")
        enriched = test_domain._enrich_command(command, True)

        with pytest.raises(RuntimeError, match="unexpected error on retry"):
            MixedErrorHandler._handle(enriched)

        assert attempt_count == 2

    @patch("protean.utils.mixins.time.sleep")
    def test_version_error_subclass_is_caught(self, mock_sleep, test_domain):
        """Subclasses of ExpectedVersionError are also retried."""

        class CustomVersionError(ExpectedVersionError):
            pass

        attempt_count = 0

        class SubclassHandler(BaseCommandHandler):
            @handle(RenameUser)
            def rename(self, command: RenameUser) -> None:
                nonlocal attempt_count
                attempt_count += 1
                if attempt_count == 1:
                    raise CustomVersionError("custom conflict")

        test_domain.register(SubclassHandler, part_of=User)
        test_domain.init(traverse=False)

        identifier = _create_user(test_domain)

        command = RenameUser(user_id=identifier, name="Jane")
        enriched = test_domain._enrich_command(command, True)
        SubclassHandler._handle(enriched)

        assert attempt_count == 2
        mock_sleep.assert_called_once()
