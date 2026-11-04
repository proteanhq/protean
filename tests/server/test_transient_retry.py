"""Tests for transient-failure auto-retry at the @handle decorator level.

Distinct from version (OCC) retry: the @handle wrapper also retries handlers
that fail with *transient* infrastructure exceptions (dropped connections,
timeouts, email-gateway blips) using a configurable backoff strategy, before
the error reaches the subscription retry/DLQ pipeline.

The policy is opt-in (disabled by default) and configurable domain-wide via
``server.transient_retry`` or per-handler via
``@domain.command_handler(retries=..., backoff=..., retry_exceptions=...)``.
"""

import logging
from datetime import UTC, datetime, timedelta
from enum import Enum
from unittest.mock import Mock, patch
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
from protean.utils.eventing import Message
from protean.utils.globals import current_domain, g
from protean.utils.mixins import (
    _TRANSIENT_RETRY_DEFAULTS,
    _deadline_exceeded_after,
    _get_transient_retry_config,
    _import_exception_type,
    _record_handler_retry,
    _resolve_exception_types,
    _transient_backoff_delay,
    handle,
)
from protean.utils.telemetry import _DOMAIN_METRICS_KEY, get_domain_metrics

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
    test_domain.register(User, event_sourced=True)
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


class CustomTransient(Exception):
    pass


@pytest.fixture
def retried_points(test_domain):
    """Send the domain's metrics to an in-memory reader.

    Returns a function that lists the ``protean.handler.retried`` data points
    recorded so far.
    """
    from opentelemetry.sdk.metrics import MeterProvider as SDKMeterProvider
    from opentelemetry.sdk.metrics.export import InMemoryMetricReader
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider as SDKTracerProvider

    resource = Resource.create({"service.name": test_domain.normalized_name})
    reader = InMemoryMetricReader()
    test_domain._otel_meter_provider = SDKMeterProvider(
        resource=resource, metric_readers=[reader]
    )
    test_domain._otel_tracer_provider = SDKTracerProvider(resource=resource)
    test_domain._otel_init_attempted = True
    if hasattr(test_domain, _DOMAIN_METRICS_KEY):
        delattr(test_domain, _DOMAIN_METRICS_KEY)

    def points() -> list:
        data = reader.get_metrics_data()
        if data is None:
            return []
        return [
            point
            for resource_metric in data.resource_metrics
            for scope_metric in resource_metric.scope_metrics
            for metric in scope_metric.metrics
            if metric.name == "protean.handler.retried"
            for point in metric.data.data_points
        ]

    yield points
    if hasattr(test_domain, _DOMAIN_METRICS_KEY):
        delattr(test_domain, _DOMAIN_METRICS_KEY)


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

    @pytest.mark.parametrize(
        "enabled, max_retries",
        [("false", 0), ("true", 3)],
    )
    def test_string_enabled_is_read_as_a_bool(self, test_domain, enabled, max_retries):
        """A string `"false"` (e.g. from env substitution) must NOT enable retry;
        a string `"true"` does."""
        test_domain.config["server"]["transient_retry"]["enabled"] = enabled
        cfg = _get_transient_retry_config(None)
        assert cfg["max_retries"] == max_retries

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
        """Retries are off by default, and exceptions are not resolved when
        retries are off, so the import cost (and any misconfiguration) is never
        paid on the disabled path."""
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

    @pytest.mark.parametrize(
        "setting, reason",
        [
            ({"max_retries": "many"}, "many"),
            ({"max_retries": float("inf")}, "infinity"),
            ({"base_delay_seconds": None}, "NoneType"),
        ],
        ids=["not-a-number", "infinite-retries", "missing-delay"],
    )
    def test_falls_back_to_defaults_on_a_value_that_does_not_convert(
        self, test_domain, caplog, setting, reason
    ):
        """A value that is not a number falls back to (disabled) defaults."""
        test_domain.config["server"]["transient_retry"] = {"enabled": True, **setting}
        with caplog.at_level(logging.WARNING, logger="protean.utils.mixins"):
            cfg = _get_transient_retry_config(None)
        assert cfg["max_retries"] == 0
        assert cfg["exceptions"] == (ConnectionError, TimeoutError, SendError)
        assert "Invalid [server.transient_retry] config" in caplog.text
        assert reason in caplog.text

    @pytest.mark.parametrize("section", ["on", False, 0, ""])
    def test_falls_back_to_defaults_when_section_is_not_a_table(
        self, test_domain, caplog, section
    ):
        test_domain.config["server"]["transient_retry"] = section
        with caplog.at_level(logging.WARNING, logger="protean.utils.mixins"):
            cfg = _get_transient_retry_config(None)
        assert cfg["max_retries"] == 0
        assert "Invalid [server.transient_retry] config" in caplog.text

    def test_an_unexpected_config_error_propagates(self, test_domain):
        """Only conversion and non-table errors fall back; others surface."""

        class BrokenTable(dict):
            def get(self, *args, **kwargs):
                raise RuntimeError("boom")

        test_domain.config["server"] = BrokenTable()

        with pytest.raises(RuntimeError, match="boom"):
            _get_transient_retry_config(None)


class TestExceptionResolution:
    @pytest.mark.parametrize(
        "path, expected",
        [
            ("ConnectionError", ConnectionError),
            ("builtins.TimeoutError", TimeoutError),
            ("protean.exceptions.SendError", SendError),
        ],
        ids=["bare-builtin", "dotted-builtin", "protean-exception"],
    )
    def test_import_exception_type(self, path, expected):
        assert _import_exception_type(path) is expected

    @pytest.mark.parametrize(
        "spec, expected",
        [
            (ConnectionError, (ConnectionError,)),
            ([ConnectionError, "builtins.OSError"], (ConnectionError, OSError)),
            # A lone dotted-path string resolves, rather than iterating chars.
            ("builtins.OSError", (OSError,)),
        ],
        ids=["single-class", "mixed-iterable", "single-dotted-string"],
    )
    def test_resolve_exception_types(self, spec, expected):
        assert _resolve_exception_types(spec) == expected

    @pytest.mark.parametrize("spec", [123, [123]], ids=["non-iterable", "bad-item"])
    def test_invalid_spec_raises_clear_error(self, spec):
        with pytest.raises(ConfigurationError, match="Invalid transient retry"):
            _resolve_exception_types(spec)

    def test_non_exception_path_raises(self):
        with pytest.raises(ConfigurationError, match="not an exception type"):
            _import_exception_type("builtins.dict")


class TestBackoffStrategies:
    @pytest.mark.parametrize(
        "strategy, base, cap, delays",
        [
            ("exponential", 0.1, 100, [0.1, 0.2, 0.4, 0.8]),
            ("linear", 0.1, 100, [0.1, 0.2, 0.3, 0.4]),
            ("fixed", 0.1, 100, [0.1, 0.1, 0.1, 0.1]),
            ("exponential", 0.5, 1.0, [0.5, 1.0, 1.0, 1.0]),
        ],
        ids=["exponential", "linear", "fixed", "capped-at-max"],
    )
    def test_delays(self, strategy, base, cap, delays):
        assert [
            _transient_backoff_delay(strategy, i, base, cap) for i in range(4)
        ] == pytest.approx(delays)


# ---------------------------------------------------------------------------
# Per-handler retry behavior
# ---------------------------------------------------------------------------


class TestTransientRetryBehavior:
    @pytest.mark.parametrize(
        "options, domain_enabled, error",
        [
            ({"retries": 3}, False, ConnectionError("transient")),
            ({}, True, ConnectionError("transient")),
            (
                {"retries": 2, "retry_exceptions": [CustomTransient]},
                False,
                CustomTransient("blip"),
            ),
            ({"retries": 2}, False, SendError("gateway blip")),
            # Transient enabled per-handler; version retry uses domain defaults.
            ({"retries": 2}, False, ExpectedVersionError("conflict")),
        ],
        ids=[
            "per-handler-retries",
            "domain-level-enable",
            "custom-exception-list",
            "send-error",
            "version-conflict",
        ],
    )
    @patch("protean.utils.mixins.time.sleep")
    def test_retries_then_succeeds(
        self, mock_sleep, test_domain, options, domain_enabled, error
    ):
        test_domain.config["server"]["transient_retry"]["enabled"] = domain_enabled
        attempts = 0

        class H(BaseCommandHandler):
            @handle(RenameUser)
            def rename(self, command: RenameUser) -> None:
                nonlocal attempts
                attempts += 1
                if attempts == 1:
                    raise error

        test_domain.register(H, part_of=User, **options)
        test_domain.init(traverse=False)

        H._handle(_enrich(test_domain))

        assert attempts == 2
        mock_sleep.assert_called_once()

    @pytest.mark.parametrize(
        "options, domain_enabled, error",
        [
            # Without opt-in, a transient error is NOT retried.
            ({}, False, ConnectionError("boom")),
            ({"retries": 3}, False, ValueError("business rule")),
            ({"retries": 0}, True, ConnectionError("boom")),
            # Overriding retry_exceptions drops the default transient set.
            (
                {"retries": 2, "retry_exceptions": [CustomTransient]},
                False,
                ConnectionError("not in custom list"),
            ),
        ],
        ids=[
            "disabled-by-default",
            "non-transient-error",
            "zero-retries-beats-domain-enable",
            "custom-list-excludes-defaults",
        ],
    )
    @patch("protean.utils.mixins.time.sleep")
    def test_error_propagates_without_retry(
        self, mock_sleep, test_domain, options, domain_enabled, error
    ):
        test_domain.config["server"]["transient_retry"]["enabled"] = domain_enabled
        attempts = 0

        class H(BaseCommandHandler):
            @handle(RenameUser)
            def rename(self, command: RenameUser) -> None:
                nonlocal attempts
                attempts += 1
                raise error

        test_domain.register(H, part_of=User, **options)
        test_domain.init(traverse=False)

        with pytest.raises(type(error), match=str(error)):
            H._handle(_enrich(test_domain))

        assert attempts == 1
        mock_sleep.assert_not_called()


class TestPerHandlerBackoff:
    @pytest.mark.parametrize(
        "backoff, base, delays",
        [
            ("fixed", 0.25, [0.25, 0.25, 0.25]),
            ("linear", 0.1, [0.1, 0.2, 0.3]),
            ("exponential", 0.1, [0.1, 0.2, 0.4]),
        ],
    )
    @patch("protean.utils.mixins.time.sleep")
    def test_exhausts_retries_with_the_handler_backoff(
        self, mock_sleep, test_domain, backoff, base, delays
    ):
        """The handler's backoff sets the delays, and the last error propagates
        once the retries run out."""
        attempts = 0

        class H(BaseCommandHandler):
            @handle(RenameUser)
            def rename(self, command: RenameUser) -> None:
                nonlocal attempts
                attempts += 1
                raise TimeoutError("still down")

        test_domain.register(H, part_of=User, retries=3, backoff=backoff)
        test_domain.init(traverse=False)
        test_domain.config["server"]["transient_retry"]["base_delay_seconds"] = base

        with pytest.raises(TimeoutError, match="still down"):
            H._handle(_enrich(test_domain))

        # initial + 3 retries = 4 attempts, 3 sleeps
        assert attempts == 4
        delays_slept = [c.args[0] for c in mock_sleep.call_args_list]
        assert delays_slept == pytest.approx(delays)


# ---------------------------------------------------------------------------
# Event handlers retry transient errors
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


class TestFreshUnitOfWorkPerAttempt:
    @patch("protean.utils.mixins.time.sleep")
    def test_each_attempt_runs_in_a_fresh_unit_of_work(self, mock_sleep, test_domain):
        """Every retry attempt runs in its own in-progress UnitOfWork, so a
        failed attempt rolls back cleanly before the next one begins."""
        from protean.utils.globals import current_uow

        seen_uows = []
        in_progress_flags = []
        attempts = 0

        class H(BaseCommandHandler):
            @handle(RenameUser)
            def rename(self, command: RenameUser) -> None:
                nonlocal attempts
                attempts += 1
                uow = current_uow._get_current_object()
                # Hold a reference so object identity can't be recycled.
                seen_uows.append(uow)
                in_progress_flags.append(uow.in_progress)
                if attempts < 3:
                    raise ConnectionError("transient")

        test_domain.register(H, part_of=User, retries=3)
        test_domain.init(traverse=False)

        H._handle(_enrich(test_domain))

        assert attempts == 3
        # Each attempt saw an active UnitOfWork...
        assert in_progress_flags == [True, True, True]
        # ...and a distinct instance — a fresh UoW per attempt.
        assert seen_uows[0] is not seen_uows[1]
        assert seen_uows[1] is not seen_uows[2]
        assert seen_uows[0] is not seen_uows[2]


# ---------------------------------------------------------------------------
# Metric
# ---------------------------------------------------------------------------


class TestTransientRetryMetric:
    @patch("protean.utils.mixins.time.sleep")
    def test_retry_records_metric(self, mock_sleep, test_domain, retried_points):
        """Each transient retry adds one to ``protean.handler.retried``."""
        recorded = []

        class H(BaseCommandHandler):
            @handle(RenameUser)
            def rename(self, command: RenameUser) -> None:
                if not recorded:
                    recorded.append(1)
                    raise ConnectionError("transient")

        test_domain.register(H, part_of=User, retries=2)
        test_domain.init(traverse=False)

        H._handle(_enrich(test_domain))

        points = retried_points()
        assert len(points) == 1
        assert points[0].value == 1
        assert dict(points[0].attributes) == {
            "handler_name": "H",
            "handler_type": "COMMAND_HANDLER",
            "exception": "ConnectionError",
        }

    @patch("protean.utils.mixins.time.sleep")
    def test_exhausted_attempt_is_not_counted_as_a_retry(
        self, mock_sleep, test_domain, retried_points
    ):
        """When the retries run out, the counter equals the retries that ran,
        not the attempts."""

        class H(BaseCommandHandler):
            @handle(RenameUser)
            def rename(self, command: RenameUser) -> None:
                raise ConnectionError("still down")

        test_domain.register(H, part_of=User, retries=2)
        test_domain.init(traverse=False)

        with pytest.raises(ConnectionError, match="still down"):
            H._handle(_enrich(test_domain))

        assert mock_sleep.call_count == 2
        points = retried_points()
        assert len(points) == 1
        assert points[0].value == 2

    @pytest.mark.parametrize(
        "error",
        [None, ValueError("business rule")],
        ids=["success", "non-transient-error"],
    )
    @patch("protean.utils.mixins.time.sleep")
    def test_metric_not_recorded_without_a_retry(
        self, mock_sleep, test_domain, retried_points, error
    ):
        """Negative path: the counter does NOT fire when no retry happens,
        even when retries are enabled.

        Guards against the `protean.handler.retried` emission drifting beyond
        its stated scope (only actual transient retries).
        """

        class H(BaseCommandHandler):
            @handle(RenameUser)
            def rename(self, command: RenameUser) -> None:
                if error is not None:
                    raise error

        test_domain.register(H, part_of=User, retries=2)
        test_domain.init(traverse=False)

        if error is None:
            H._handle(_enrich(test_domain))
        else:
            with pytest.raises(ValueError):
                H._handle(_enrich(test_domain))

        assert retried_points() == []


class TestRecordHandlerRetry:
    """The metric-recording helper records nothing without a domain, labels a
    handler with no element type, and never lets a metric failure propagate."""

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

    def test_records_without_element_type(self, test_domain, retried_points, caplog):
        """A handler with no element type is labelled 'unknown', and a recorded
        metric logs nothing."""
        caplog.set_level(logging.DEBUG, logger="protean.utils.mixins")

        _record_handler_retry(self._Dummy(), ConnectionError("x"))

        points = retried_points()
        assert len(points) == 1
        assert dict(points[0].attributes)["handler_type"] == "unknown"
        assert not [
            r
            for r in caplog.records
            if r.name == "protean.utils.mixins"
            and r.getMessage().startswith("Could not record the handler retry metric")
        ]

    def test_swallows_metric_errors(self, test_domain, caplog):
        """A failure inside metric recording never propagates, and is logged."""
        caplog.set_level(logging.DEBUG, logger="protean.utils.mixins")
        failing = Mock()
        failing.add = Mock(side_effect=RuntimeError("metrics down"))
        get_domain_metrics(test_domain).handler_retried = failing

        # Must not raise — metrics must never break the retry path.
        _record_handler_retry(self._Dummy(), ConnectionError("x"))

        records = [
            r
            for r in caplog.records
            if r.name == "protean.utils.mixins"
            and r.getMessage() == "Could not record the handler retry metric for _Dummy"
        ]
        assert len(records) == 1
        assert records[0].levelno == logging.DEBUG
        assert str(records[0].exc_info[1]) == "metrics down"


# ---------------------------------------------------------------------------
# Interaction with the command deadline
#
# A retrying handler must never sleep into an attempt that would start past
# the command's deadline — that would execute the handler after its timeout,
# defeating the deadline contract. The retry loop reads the deadline from the
# in-context message and stops (re-raises) instead of sleeping past it.
# ---------------------------------------------------------------------------


def _message_with_deadline(test_domain, deadline):
    """Build an in-context message carrying a command ``deadline``."""
    command = RenameUser(user_id=str(uuid4()), name="Jane")
    enriched = test_domain._command_processor.enrich(
        command, asynchronous=True, deadline=deadline
    )
    return Message.from_domain_object(enriched)


class TestDeadlineExceededHelper:
    """Unit tests for the retry deadline guard."""

    @pytest.fixture(autouse=True)
    def _clear_context(self):
        yield
        g.pop("message_in_context", None)

    def test_no_message_context_is_unconstrained(self, test_domain):
        g.pop("message_in_context", None)
        assert _deadline_exceeded_after(10.0) is False

    def test_no_domain_context_is_unconstrained(self, test_domain):
        """Without an active domain context, `g` is unbound; the guard returns
        False (unconstrained) instead of raising, keeping the retry wrapper
        robust for handlers invoked outside a domain context."""
        from protean.utils.globals import _domain_context_stack

        ctx = _domain_context_stack.pop()
        try:
            assert _deadline_exceeded_after(10.0) is False
        finally:
            _domain_context_stack.push(ctx)

    def test_message_without_deadline_is_unconstrained(self, test_domain):
        g.message_in_context = _message_with_deadline(test_domain, None)
        assert _deadline_exceeded_after(10.0) is False

    @pytest.mark.parametrize(
        "offset, delay, exceeded",
        [
            (timedelta(seconds=-1), 0.0, True),
            (timedelta(minutes=5), 0.1, False),
            # Sleeping an hour would start the next attempt well past the deadline.
            (timedelta(seconds=1), 3600.0, True),
        ],
        ids=["past-deadline", "far-future-deadline", "deadline-within-backoff"],
    )
    def test_deadline_against_the_next_attempt(
        self, test_domain, offset, delay, exceeded
    ):
        deadline = datetime.now(UTC) + offset
        g.message_in_context = _message_with_deadline(test_domain, deadline)
        assert _deadline_exceeded_after(delay) is exceeded


class TestRetryRespectsDeadline:
    @pytest.fixture(autouse=True)
    def _clear_context(self):
        yield
        g.pop("message_in_context", None)

    @pytest.mark.parametrize(
        "offset, backoff, base",
        [
            (timedelta(seconds=-1), "exponential", None),
            # Huge backoff so the next attempt would start past the 1s deadline.
            (timedelta(seconds=1), "fixed", 3600),
        ],
        ids=["deadline-passed", "deadline-within-backoff"],
    )
    @patch("protean.utils.mixins.time.sleep")
    def test_transient_retry_stops_at_the_deadline(
        self, mock_sleep, test_domain, offset, backoff, base
    ):
        """An elapsed deadline, or a backoff that would push the next attempt
        past it, suppresses the transient retry."""
        attempts = 0

        class H(BaseCommandHandler):
            @handle(RenameUser)
            def rename(self, command: RenameUser) -> None:
                nonlocal attempts
                attempts += 1
                raise ConnectionError("transient")

        test_domain.register(H, part_of=User, retries=3, backoff=backoff)
        test_domain.init(traverse=False)
        if base is not None:
            test_domain.config["server"]["transient_retry"]["base_delay_seconds"] = base

        deadline = datetime.now(UTC) + offset
        g.message_in_context = _message_with_deadline(test_domain, deadline)
        with pytest.raises(ConnectionError):
            H._handle(_enrich(test_domain))

        assert attempts == 1  # first attempt only — no retry past the deadline
        mock_sleep.assert_not_called()

    @patch("protean.utils.mixins.time.sleep")
    def test_retry_proceeds_when_deadline_far_future(self, mock_sleep, test_domain):
        """A far-future deadline does not interfere with normal retries."""
        future = datetime.now(UTC) + timedelta(minutes=5)
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

        g.message_in_context = _message_with_deadline(test_domain, future)
        H._handle(_enrich(test_domain))

        assert attempts == 2  # retried normally; the guard did not interfere
        mock_sleep.assert_called_once()

    @patch("protean.utils.mixins.time.sleep")
    def test_version_retry_stops_when_deadline_passed(self, mock_sleep, test_domain):
        """The version (OCC) retry branch also halts at the deadline."""
        past = datetime.now(UTC) - timedelta(seconds=1)
        attempts = 0

        class H(BaseCommandHandler):
            @handle(RenameUser)
            def rename(self, command: RenameUser) -> None:
                nonlocal attempts
                attempts += 1
                raise ExpectedVersionError("conflict")

        test_domain.register(H, part_of=User)
        test_domain.init(traverse=False)

        g.message_in_context = _message_with_deadline(test_domain, past)
        with pytest.raises(ExpectedVersionError):
            H._handle(_enrich(test_domain))

        assert attempts == 1
        mock_sleep.assert_not_called()


# ---------------------------------------------------------------------------
# Nested handlers
# ---------------------------------------------------------------------------


class Account(BaseAggregate):
    name: String(max_length=50)


class OpenAccount(BaseCommand):
    account_id: Identifier(required=True)


class WriteAccount(BaseCommand):
    account_id: Identifier(required=True)


class TestNestedHandlerTransientRetry:
    @patch("protean.utils.mixins.time.sleep")
    def test_transient_error_in_nested_handler_is_retried_by_the_outer_handler(
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
                    raise ConnectionError("transient")
                current_domain.repository_for(Account).add(
                    Account(id=command.account_id, name="written")
                )

        test_domain.register(Account)
        test_domain.register(OpenAccount, part_of=Account)
        test_domain.register(WriteAccount, part_of=Account)
        test_domain.register(AccountHandlers, part_of=Account)
        test_domain.init(traverse=False)
        test_domain.config["server"]["transient_retry"]["enabled"] = True
        test_domain.config["server"]["transient_retry"]["exceptions"] = [
            "ConnectionError"
        ]

        test_domain.process(OpenAccount(account_id="a1"), asynchronous=False)

        assert inner_runs == 2
        assert outer_runs == 2
        account = test_domain.repository_for(Account).get_or_none("a1")
        assert account is not None
        assert account.name == "written"
        mock_sleep.assert_called_once()

    @patch("protean.utils.mixins.time.sleep")
    def test_transient_error_inside_an_open_unit_of_work_is_not_retried(
        self, mock_sleep, test_domain
    ):
        runs = 0

        class AccountHandlers(BaseCommandHandler):
            @handle(WriteAccount)
            def write(self, command: WriteAccount) -> None:
                nonlocal runs
                runs += 1
                raise ConnectionError("transient")

        test_domain.register(Account)
        test_domain.register(WriteAccount, part_of=Account)
        test_domain.register(AccountHandlers, part_of=Account)
        test_domain.init(traverse=False)
        test_domain.config["server"]["transient_retry"]["enabled"] = True
        test_domain.config["server"]["transient_retry"]["exceptions"] = [
            "ConnectionError"
        ]

        with pytest.raises(ConnectionError):
            with UnitOfWork():
                test_domain.process(WriteAccount(account_id="a1"), asynchronous=False)

        assert runs == 1
        mock_sleep.assert_not_called()

    @patch("protean.utils.mixins.time.sleep")
    def test_a_nested_handlers_own_retry_policy_does_not_apply(
        self, mock_sleep, test_domain
    ):
        runs = {"outer": 0, "inner": 0}

        class OuterHandlers(BaseCommandHandler):
            @handle(OpenAccount)
            def open(self, command: OpenAccount) -> None:
                runs["outer"] += 1
                current_domain.process(
                    WriteAccount(account_id=command.account_id), asynchronous=False
                )

        class InnerHandlers(BaseCommandHandler):
            @handle(WriteAccount)
            def write(self, command: WriteAccount) -> None:
                runs["inner"] += 1
                raise ConnectionError("transient")

        test_domain.register(Account)
        test_domain.register(OpenAccount, part_of=Account)
        test_domain.register(WriteAccount, part_of=Account)
        test_domain.register(OuterHandlers, part_of=Account)
        test_domain.register(
            InnerHandlers,
            part_of=Account,
            retries=3,
            retry_exceptions=[ConnectionError],
        )
        test_domain.init(traverse=False)

        with pytest.raises(ConnectionError):
            test_domain.process(OpenAccount(account_id="a1"), asynchronous=False)

        assert runs == {"outer": 1, "inner": 1}
        mock_sleep.assert_not_called()
