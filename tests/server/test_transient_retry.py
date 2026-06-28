"""Tests for transient-failure auto-retry at the @handle decorator level.

Distinct from version (OCC) retry: the @handle wrapper also retries handlers
that fail with *transient* infrastructure exceptions (dropped connections,
timeouts, email-gateway blips) using a configurable backoff strategy, before
the error reaches the subscription retry/DLQ pipeline.

The policy is opt-in (disabled by default) and configurable domain-wide via
``server.transient_retry`` or per-handler via
``@domain.command_handler(retries=..., backoff=..., retry_exceptions=...)``.
"""

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
from protean.exceptions import ConfigurationError, ExpectedVersionError, SendError
from protean.fields import Identifier, String
from protean.utils.globals import current_domain
from protean.utils.mixins import (
    _TRANSIENT_RETRY_DEFAULTS,
    _get_transient_retry_config,
    _import_exception_type,
    _record_handler_retry,
    _resolve_exception_types,
    _transient_backoff_delay,
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

    def change_name(self, name: str) -> None:
        self.raise_(UserRenamed(user_id=self.user_id, name=name))

    @apply
    def registered(self, event: UserRegistered) -> None:
        self.user_id = event.user_id
        self.name = event.name
        self.email = event.email
        self.status = UserStatus.INACTIVE.value

    @apply
    def renamed(self, event: UserRenamed) -> None:
        self.name = event.name


class RenameUser(BaseCommand):
    user_id: Identifier(required=True)
    name: String(required=True, max_length=50)


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(User, is_event_sourced=True)
    test_domain.register(UserRegistered, part_of=User)
    test_domain.register(UserRenamed, part_of=User)
    test_domain.register(RenameUser, part_of=User)
    test_domain.init(traverse=False)


def _create_user(test_domain) -> str:
    identifier = str(uuid4())
    with UnitOfWork():
        repo = test_domain.repository_for(User)
        user = User.register(user_id=identifier, name="John", email="john@example.com")
        repo.add(user)
    return identifier


def _enrich(test_domain, name="Jane"):
    command = RenameUser(user_id=str(uuid4()), name=name)
    return test_domain._enrich_command(command, True)


# ---------------------------------------------------------------------------
# Configuration tests
# ---------------------------------------------------------------------------


class TestTransientRetryDefaults:
    def test_default_values(self):
        assert _TRANSIENT_RETRY_DEFAULTS["enabled"] is False
        assert _TRANSIENT_RETRY_DEFAULTS["max_retries"] == 3
        assert _TRANSIENT_RETRY_DEFAULTS["backoff"] == "exponential"
        assert _TRANSIENT_RETRY_DEFAULTS["base_delay_seconds"] == 0.1
        assert _TRANSIENT_RETRY_DEFAULTS["max_delay_seconds"] == 5.0
        assert _TRANSIENT_RETRY_DEFAULTS["exceptions"] == (
            ConnectionError,
            TimeoutError,
            SendError,
        )

    def test_disabled_by_default_yields_zero_max(self, test_domain):
        """With the default (disabled) config, no retries are attempted."""
        cfg = _get_transient_retry_config(None)
        assert cfg["max_retries"] == 0

    def test_domain_config_has_transient_retry_section(self, test_domain):
        section = test_domain.config.get("server", {}).get("transient_retry", {})
        for key in (
            "enabled",
            "max_retries",
            "backoff",
            "base_delay_seconds",
            "max_delay_seconds",
            "exceptions",
        ):
            assert key in section

    def test_default_exceptions_resolved_from_dotted_paths(self, test_domain):
        """The dotted-path strings in domain config resolve to classes."""
        test_domain.config["server"]["transient_retry"]["enabled"] = True
        cfg = _get_transient_retry_config(None)
        assert cfg["exceptions"] == (ConnectionError, TimeoutError, SendError)
        assert cfg["max_retries"] == 3

    def test_custom_overrides(self, test_domain):
        test_domain.config["server"]["transient_retry"] = {
            "enabled": True,
            "max_retries": 5,
            "backoff": "linear",
            "base_delay_seconds": 0.2,
            "max_delay_seconds": 9.0,
            "exceptions": ["builtins.OSError"],
        }
        cfg = _get_transient_retry_config(None)
        assert cfg["max_retries"] == 5
        assert cfg["backoff"] == "linear"
        assert cfg["base_delay_seconds"] == 0.2
        assert cfg["max_delay_seconds"] == 9.0
        assert cfg["exceptions"] == (OSError,)

    def test_string_enabled_false_stays_disabled(self, test_domain):
        """A string `"false"` (e.g. from env substitution) must NOT enable retry."""
        test_domain.config["server"]["transient_retry"]["enabled"] = "false"
        cfg = _get_transient_retry_config(None)
        assert cfg["max_retries"] == 0

    def test_string_enabled_true_enables(self, test_domain):
        """A string `"true"` enables retry."""
        test_domain.config["server"]["transient_retry"]["enabled"] = "true"
        cfg = _get_transient_retry_config(None)
        assert cfg["max_retries"] == 3

    def test_invalid_backoff_raises(self, test_domain):
        test_domain.config["server"]["transient_retry"]["enabled"] = True
        test_domain.config["server"]["transient_retry"]["backoff"] = "quadratic"
        with pytest.raises(ConfigurationError, match="Invalid transient retry backoff"):
            _get_transient_retry_config(None)

    def test_invalid_exception_path_raises_when_active(self, test_domain):
        """A bad exception spec is resolved (and rejected) when retries are on."""
        test_domain.config["server"]["transient_retry"]["enabled"] = True
        test_domain.config["server"]["transient_retry"]["exceptions"] = [
            "builtins.NoSuchError"
        ]
        with pytest.raises(ConfigurationError, match="Cannot resolve"):
            _get_transient_retry_config(None)

    def test_invalid_exception_path_ignored_when_disabled(self, test_domain):
        """Exceptions are not resolved when retries are off, so the import cost
        (and any misconfiguration) is never paid on the disabled path."""
        test_domain.config["server"]["transient_retry"]["enabled"] = False
        test_domain.config["server"]["transient_retry"]["exceptions"] = [
            "builtins.NoSuchError"
        ]
        cfg = _get_transient_retry_config(None)  # does not raise
        assert cfg["max_retries"] == 0
        assert cfg["exceptions"] == (ConnectionError, TimeoutError, SendError)

    def test_falls_back_to_defaults_when_no_domain_active(self, test_domain):
        from protean.utils.globals import _domain_context_stack

        ctx = _domain_context_stack.pop()
        try:
            cfg = _get_transient_retry_config(None)
            # Disabled default -> 0 effective retries
            assert cfg["max_retries"] == 0
            assert cfg["exceptions"] == (ConnectionError, TimeoutError, SendError)
        finally:
            _domain_context_stack.push(ctx)

    def test_falls_back_to_defaults_on_config_error(self, test_domain):
        """A failure reading config falls back to (disabled) defaults."""
        with patch.object(
            type(test_domain.config), "get", side_effect=RuntimeError("boom")
        ):
            cfg = _get_transient_retry_config(None)
        assert cfg["max_retries"] == 0
        assert cfg["exceptions"] == (ConnectionError, TimeoutError, SendError)


class TestExceptionResolution:
    def test_resolves_bare_builtin_name(self):
        assert _import_exception_type("ConnectionError") is ConnectionError

    def test_resolves_dotted_builtin(self):
        assert _import_exception_type("builtins.TimeoutError") is TimeoutError

    def test_resolves_protean_exception(self):
        assert _import_exception_type("protean.exceptions.SendError") is SendError

    def test_single_class_wrapped_in_tuple(self):
        assert _resolve_exception_types(ConnectionError) == (ConnectionError,)

    def test_mixed_iterable(self):
        assert _resolve_exception_types([ConnectionError, "builtins.OSError"]) == (
            ConnectionError,
            OSError,
        )

    def test_single_dotted_string_not_iterated_as_chars(self):
        """A lone dotted-path string resolves, rather than iterating chars."""
        assert _resolve_exception_types("builtins.OSError") == (OSError,)

    def test_non_iterable_spec_raises_clear_error(self):
        with pytest.raises(ConfigurationError, match="Invalid transient retry"):
            _resolve_exception_types(123)

    def test_unknown_path_raises(self):
        with pytest.raises(ConfigurationError, match="Cannot resolve"):
            _import_exception_type("builtins.NoSuchError")

    def test_non_exception_path_raises(self):
        with pytest.raises(ConfigurationError, match="not an exception type"):
            _import_exception_type("builtins.dict")

    def test_invalid_spec_type_raises(self):
        with pytest.raises(ConfigurationError, match="Invalid transient retry"):
            _resolve_exception_types([123])


class TestBackoffStrategies:
    def test_exponential(self):
        delays = [
            _transient_backoff_delay("exponential", i, 0.1, 100) for i in range(4)
        ]
        assert delays == pytest.approx([0.1, 0.2, 0.4, 0.8])

    def test_linear(self):
        delays = [_transient_backoff_delay("linear", i, 0.1, 100) for i in range(4)]
        assert delays == pytest.approx([0.1, 0.2, 0.3, 0.4])

    def test_fixed(self):
        delays = [_transient_backoff_delay("fixed", i, 0.1, 100) for i in range(4)]
        assert delays == pytest.approx([0.1, 0.1, 0.1, 0.1])

    def test_capped_at_max(self):
        assert _transient_backoff_delay("exponential", 10, 0.5, 1.0) == 1.0


# ---------------------------------------------------------------------------
# Per-handler retry behavior
# ---------------------------------------------------------------------------


class TestTransientRetryBehavior:
    @patch("protean.utils.mixins.time.sleep")
    def test_disabled_by_default_propagates(self, mock_sleep, test_domain):
        """Without opt-in, a transient error is NOT retried."""
        attempts = 0

        class H(BaseCommandHandler):
            @handle(RenameUser)
            def rename(self, command: RenameUser) -> None:
                nonlocal attempts
                attempts += 1
                raise ConnectionError("boom")

        test_domain.register(H, part_of=User)
        test_domain.init(traverse=False)

        with pytest.raises(ConnectionError):
            H._handle(_enrich(test_domain))

        assert attempts == 1
        mock_sleep.assert_not_called()

    @patch("protean.utils.mixins.time.sleep")
    def test_per_handler_retries_then_succeeds(self, mock_sleep, test_domain):
        attempts = 0

        class H(BaseCommandHandler):
            @handle(RenameUser)
            def rename(self, command: RenameUser) -> None:
                nonlocal attempts
                attempts += 1
                if attempts == 1:
                    raise ConnectionError("transient")

        test_domain.register(H, part_of=User, retries=3)
        test_domain.init(traverse=False)

        H._handle(_enrich(test_domain))

        assert attempts == 2
        mock_sleep.assert_called_once()

    @patch("protean.utils.mixins.time.sleep")
    def test_exhausts_retries_and_raises(self, mock_sleep, test_domain):
        attempts = 0

        class H(BaseCommandHandler):
            @handle(RenameUser)
            def rename(self, command: RenameUser) -> None:
                nonlocal attempts
                attempts += 1
                raise TimeoutError("still down")

        test_domain.register(H, part_of=User, retries=3)
        test_domain.init(traverse=False)

        with pytest.raises(TimeoutError, match="still down"):
            H._handle(_enrich(test_domain))

        # initial + 3 retries = 4 attempts, 3 sleeps
        assert attempts == 4
        assert mock_sleep.call_count == 3

    @patch("protean.utils.mixins.time.sleep")
    def test_non_transient_error_propagates_immediately(self, mock_sleep, test_domain):
        attempts = 0

        class H(BaseCommandHandler):
            @handle(RenameUser)
            def rename(self, command: RenameUser) -> None:
                nonlocal attempts
                attempts += 1
                raise ValueError("business rule")

        test_domain.register(H, part_of=User, retries=3)
        test_domain.init(traverse=False)

        with pytest.raises(ValueError, match="business rule"):
            H._handle(_enrich(test_domain))

        assert attempts == 1
        mock_sleep.assert_not_called()

    @patch("protean.utils.mixins.time.sleep")
    def test_zero_retries_disables_even_when_domain_enabled(
        self, mock_sleep, test_domain
    ):
        test_domain.config["server"]["transient_retry"]["enabled"] = True

        class H(BaseCommandHandler):
            @handle(RenameUser)
            def rename(self, command: RenameUser) -> None:
                raise ConnectionError("boom")

        test_domain.register(H, part_of=User, retries=0)
        test_domain.init(traverse=False)

        with pytest.raises(ConnectionError):
            H._handle(_enrich(test_domain))

        mock_sleep.assert_not_called()

    @patch("protean.utils.mixins.time.sleep")
    def test_domain_level_enable_applies_without_per_handler_opt(
        self, mock_sleep, test_domain
    ):
        test_domain.config["server"]["transient_retry"]["enabled"] = True
        attempts = 0

        class H(BaseCommandHandler):
            @handle(RenameUser)
            def rename(self, command: RenameUser) -> None:
                nonlocal attempts
                attempts += 1
                if attempts == 1:
                    raise ConnectionError("transient")

        test_domain.register(H, part_of=User)
        test_domain.init(traverse=False)

        H._handle(_enrich(test_domain))

        assert attempts == 2
        mock_sleep.assert_called_once()

    @patch("protean.utils.mixins.time.sleep")
    def test_per_handler_retry_exceptions_override(self, mock_sleep, test_domain):
        """A custom exception list retries only the listed types."""

        class CustomTransient(Exception):
            pass

        attempts = 0

        class H(BaseCommandHandler):
            @handle(RenameUser)
            def rename(self, command: RenameUser) -> None:
                nonlocal attempts
                attempts += 1
                if attempts == 1:
                    raise CustomTransient("blip")

        test_domain.register(
            H, part_of=User, retries=2, retry_exceptions=[CustomTransient]
        )
        test_domain.init(traverse=False)

        H._handle(_enrich(test_domain))
        assert attempts == 2

    @patch("protean.utils.mixins.time.sleep")
    def test_retry_exceptions_override_excludes_defaults(self, mock_sleep, test_domain):
        """Overriding retry_exceptions drops the default transient set."""

        class CustomTransient(Exception):
            pass

        attempts = 0

        class H(BaseCommandHandler):
            @handle(RenameUser)
            def rename(self, command: RenameUser) -> None:
                nonlocal attempts
                attempts += 1
                raise ConnectionError("not in custom list")

        test_domain.register(
            H, part_of=User, retries=2, retry_exceptions=[CustomTransient]
        )
        test_domain.init(traverse=False)

        with pytest.raises(ConnectionError):
            H._handle(_enrich(test_domain))
        assert attempts == 1  # ConnectionError no longer transient
        mock_sleep.assert_not_called()

    @patch("protean.utils.mixins.time.sleep")
    def test_send_error_is_transient(self, mock_sleep, test_domain):
        attempts = 0

        class H(BaseCommandHandler):
            @handle(RenameUser)
            def rename(self, command: RenameUser) -> None:
                nonlocal attempts
                attempts += 1
                if attempts == 1:
                    raise SendError("gateway blip")

        test_domain.register(H, part_of=User, retries=2)
        test_domain.init(traverse=False)

        H._handle(_enrich(test_domain))
        assert attempts == 2


class TestPerHandlerBackoff:
    @patch("protean.utils.mixins.time.sleep")
    def test_fixed_backoff(self, mock_sleep, test_domain):
        class H(BaseCommandHandler):
            @handle(RenameUser)
            def rename(self, command: RenameUser) -> None:
                raise ConnectionError("down")

        test_domain.register(H, part_of=User, retries=3, backoff="fixed")
        test_domain.init(traverse=False)
        test_domain.config["server"]["transient_retry"]["base_delay_seconds"] = 0.25

        with pytest.raises(ConnectionError):
            H._handle(_enrich(test_domain))

        delays = [c.args[0] for c in mock_sleep.call_args_list]
        assert delays == pytest.approx([0.25, 0.25, 0.25])

    @patch("protean.utils.mixins.time.sleep")
    def test_linear_backoff(self, mock_sleep, test_domain):
        class H(BaseCommandHandler):
            @handle(RenameUser)
            def rename(self, command: RenameUser) -> None:
                raise ConnectionError("down")

        test_domain.register(H, part_of=User, retries=3, backoff="linear")
        test_domain.init(traverse=False)
        test_domain.config["server"]["transient_retry"]["base_delay_seconds"] = 0.1

        with pytest.raises(ConnectionError):
            H._handle(_enrich(test_domain))

        delays = [c.args[0] for c in mock_sleep.call_args_list]
        assert delays == pytest.approx([0.1, 0.2, 0.3])

    @patch("protean.utils.mixins.time.sleep")
    def test_exponential_backoff(self, mock_sleep, test_domain):
        class H(BaseCommandHandler):
            @handle(RenameUser)
            def rename(self, command: RenameUser) -> None:
                raise ConnectionError("down")

        test_domain.register(H, part_of=User, retries=3, backoff="exponential")
        test_domain.init(traverse=False)
        test_domain.config["server"]["transient_retry"]["base_delay_seconds"] = 0.1

        with pytest.raises(ConnectionError):
            H._handle(_enrich(test_domain))

        delays = [c.args[0] for c in mock_sleep.call_args_list]
        assert delays == pytest.approx([0.1, 0.2, 0.4])


# ---------------------------------------------------------------------------
# Event handler coverage
# ---------------------------------------------------------------------------


class TestEventHandlerTransientRetry:
    @patch("protean.utils.mixins.time.sleep")
    def test_event_handler_retries_on_transient(self, mock_sleep, test_domain):
        attempts = 0

        class EH(BaseEventHandler):
            @handle(UserRegistered)
            def on_registered(self, event: UserRegistered) -> None:
                nonlocal attempts
                attempts += 1
                if attempts == 1:
                    raise ConnectionError("transient")

        test_domain.register(EH, part_of=User, retries=2)
        test_domain.init(traverse=False)

        event = UserRegistered(
            user_id=str(uuid4()), name="John", email="john@example.com"
        )
        EH._handle(event)

        assert attempts == 2
        mock_sleep.assert_called_once()


# ---------------------------------------------------------------------------
# Interaction with version (OCC) retry
# ---------------------------------------------------------------------------


class TestVersionAndTransientInteraction:
    @patch("protean.utils.mixins.time.sleep")
    def test_version_retry_still_works_when_transient_enabled(
        self, mock_sleep, test_domain
    ):
        attempts = 0

        class H(BaseCommandHandler):
            @handle(RenameUser)
            def rename(self, command: RenameUser) -> None:
                nonlocal attempts
                attempts += 1
                if attempts == 1:
                    raise ExpectedVersionError("conflict")

        # Transient enabled per-handler; version retry uses domain defaults.
        test_domain.register(H, part_of=User, retries=2)
        test_domain.init(traverse=False)

        H._handle(_enrich(test_domain))
        assert attempts == 2

    @patch("protean.utils.mixins.time.sleep")
    def test_independent_counters(self, mock_sleep, test_domain):
        """Version and transient retries use separate budgets."""
        attempts = 0

        class H(BaseCommandHandler):
            @handle(RenameUser)
            def rename(self, command: RenameUser) -> None:
                nonlocal attempts
                attempts += 1
                if attempts == 1:
                    raise ExpectedVersionError("version conflict")
                if attempts == 2:
                    raise ConnectionError("transient")

        test_domain.register(H, part_of=User, retries=1)
        test_domain.init(traverse=False)

        H._handle(_enrich(test_domain))
        # 1: version conflict (version retry), 2: transient (transient retry), 3: ok
        assert attempts == 3


# ---------------------------------------------------------------------------
# Metric
# ---------------------------------------------------------------------------


class TestTransientRetryMetric:
    def test_handler_retried_counter_registered(self, test_domain):
        from protean.utils.telemetry import get_domain_metrics

        metrics = get_domain_metrics(current_domain)
        assert hasattr(metrics, "handler_retried")

    @patch("protean.utils.mixins.time.sleep")
    def test_retry_records_metric(self, mock_sleep, test_domain):
        """The retry path increments the counter without raising."""
        recorded = []

        class H(BaseCommandHandler):
            @handle(RenameUser)
            def rename(self, command: RenameUser) -> None:
                if not recorded:
                    recorded.append(1)
                    raise ConnectionError("transient")

        test_domain.register(H, part_of=User, retries=2)
        test_domain.init(traverse=False)

        with patch("protean.utils.mixins._record_handler_retry") as rec:
            H._handle(_enrich(test_domain))
            assert rec.call_count == 1

    @patch("protean.utils.mixins.time.sleep")
    def test_metric_not_recorded_on_success(self, mock_sleep, test_domain):
        """Negative path: the counter does NOT fire when no retry happens.

        Guards against the `protean.handler.retried` emission drifting beyond
        its stated scope (only actual transient retries).
        """

        class H(BaseCommandHandler):
            @handle(RenameUser)
            def rename(self, command: RenameUser) -> None:
                pass  # succeeds immediately

        test_domain.register(H, part_of=User, retries=2)
        test_domain.init(traverse=False)

        with patch("protean.utils.mixins._record_handler_retry") as rec:
            H._handle(_enrich(test_domain))
            rec.assert_not_called()

    @patch("protean.utils.mixins.time.sleep")
    def test_metric_not_recorded_for_non_transient_error(self, mock_sleep, test_domain):
        """Negative path: a non-transient error propagates without a retry
        metric, even when retries are enabled."""

        class H(BaseCommandHandler):
            @handle(RenameUser)
            def rename(self, command: RenameUser) -> None:
                raise ValueError("business rule")

        test_domain.register(H, part_of=User, retries=2)
        test_domain.init(traverse=False)

        with patch("protean.utils.mixins._record_handler_retry") as rec:
            with pytest.raises(ValueError):
                H._handle(_enrich(test_domain))
            rec.assert_not_called()


class TestRecordHandlerRetry:
    """Direct tests for the metric-recording helper's guard branches."""

    class _Dummy:
        element_type = None

    def test_no_op_without_active_domain(self, test_domain):
        """Returns quietly when no domain context is active."""
        from protean.utils.globals import _domain_context_stack

        ctx = _domain_context_stack.pop()
        try:
            # Must not raise even though there is no domain to record against.
            _record_handler_retry(self._Dummy(), ConnectionError("x"))
        finally:
            _domain_context_stack.push(ctx)

    def test_records_without_element_type(self, test_domain):
        """The `element_type is None` branch labels handler_type 'unknown'."""
        # Real (no-op) metrics registry; just assert it does not raise.
        _record_handler_retry(self._Dummy(), ConnectionError("x"))

    def test_swallows_metric_errors(self, test_domain):
        """A failure inside metric recording never propagates."""
        with patch(
            "protean.utils.telemetry.get_domain_metrics",
            side_effect=RuntimeError("metrics down"),
        ):
            # Must not raise — metrics must never break the retry path.
            _record_handler_retry(self._Dummy(), ConnectionError("x"))
