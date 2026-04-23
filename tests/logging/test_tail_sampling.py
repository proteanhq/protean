"""Tests for tail sampling of wide events.

Verifies that:
- Sampling is opt-in (disabled by default — all wide events emit)
- Errors are always kept (regardless of default_rate)
- Slow handlers are always kept
- ``critical_streams`` glob patterns are always kept
- Random sampling respects ``default_rate`` deterministically at 0.0 and 1.0
- Sampling metadata (``sampling_decision``, ``sampling_rule``, ``sampling_rate``)
  is present on kept events
- Non-access loggers are never affected, even at ``default_rate=0.0``
- ``critical_streams`` uses fnmatch glob semantics
- ``Domain.configure_logging()`` installs the filter when sampling is enabled
"""

import logging
import time
from pathlib import Path
from typing import Iterator
from unittest.mock import patch
from uuid import uuid4

import pytest
import structlog

from protean import Domain
from protean.core.aggregate import BaseAggregate
from protean.core.command import BaseCommand
from protean.core.command_handler import BaseCommandHandler
from protean.fields import Identifier, String
from protean.utils.logging import TailSamplingFilter, TailSamplingProcessor
from protean.utils.mixins import handle


# --- Domain elements ---


class Widget(BaseAggregate):
    widget_id = Identifier(identifier=True)
    name = String()


class PlaceOrder(BaseCommand):
    widget_id = Identifier(identifier=True)
    name = String()


class UpdateProfile(BaseCommand):
    widget_id = Identifier(identifier=True)
    name = String()


class FailingCommand(BaseCommand):
    widget_id = Identifier(identifier=True)


class SuccessHandler(BaseCommandHandler):
    @handle(PlaceOrder)
    def handle_place(self, command: PlaceOrder) -> None:
        pass


class UpdateHandler(BaseCommandHandler):
    @handle(UpdateProfile)
    def handle_update(self, command: UpdateProfile) -> None:
        pass


class SlowHandler(BaseCommandHandler):
    @handle(PlaceOrder)
    def handle_slow(self, command: PlaceOrder) -> None:
        time.sleep(0.06)  # 60ms — slow at a 10ms threshold


class FailingHandler(BaseCommandHandler):
    @handle(FailingCommand)
    def handle_fail(self, command: FailingCommand) -> None:
        raise ValueError("boom")


def _access_records(caplog) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.name == "protean.access"]


def _fake_access_record(
    level: int = logging.INFO,
    status: str = "ok",
    message_type: str = "SomeCommand",
    name: str = "protean.access",
) -> logging.LogRecord:
    """Build a LogRecord as if emitted by the access logger for filter tests."""
    record = logging.LogRecord(
        name=name,
        level=level,
        pathname="",
        lineno=0,
        msg="access.handler_completed",
        args=(),
        exc_info=None,
    )
    record.status = status  # type: ignore[attr-defined]
    record.message_type = message_type  # type: ignore[attr-defined]
    return record


@pytest.fixture
def install_sampling_filter() -> Iterator:
    """Install a ``TailSamplingFilter`` on ``protean.access`` with cleanup.

    The fixture returns a callable that takes the filter's keyword arguments
    and installs the filter. Teardown removes any filter installed during
    the test so later tests see a clean ``protean.access`` logger.
    """
    access_logger = logging.getLogger("protean.access")
    original_filters = list(access_logger.filters)
    installed: list[TailSamplingFilter] = []

    def _install(**kwargs) -> TailSamplingFilter:
        f = TailSamplingFilter(**kwargs)
        access_logger.addFilter(f)
        installed.append(f)
        return f

    try:
        yield _install
    finally:
        for f in installed:
            access_logger.removeFilter(f)
        access_logger.filters = original_filters


# ---------------------------------------------------------------------------
# Filter unit tests — rule ordering and metadata
# ---------------------------------------------------------------------------


class TestTailSamplingFilterRules:
    """Rules evaluated in order — first match wins."""

    def test_errors_always_kept_at_zero_rate(self):
        f = TailSamplingFilter(default_rate=0.0)
        record = _fake_access_record(level=logging.ERROR, status="failed")
        assert f.filter(record) is True
        assert record.sampling_decision == "kept"  # type: ignore[attr-defined]
        assert record.sampling_rule == "error"  # type: ignore[attr-defined]
        assert record.sampling_rate == 1.0  # type: ignore[attr-defined]

    def test_error_level_kept_even_without_failed_status(self):
        """A record with status='ok' but level=ERROR still counts as error."""
        f = TailSamplingFilter(default_rate=0.0)
        record = _fake_access_record(level=logging.ERROR, status="ok")
        assert f.filter(record) is True
        assert record.sampling_rule == "error"  # type: ignore[attr-defined]

    def test_slow_always_kept_at_zero_rate(self):
        f = TailSamplingFilter(default_rate=0.0)
        record = _fake_access_record(status="slow", level=logging.WARNING)
        assert f.filter(record) is True
        assert record.sampling_rule == "slow"  # type: ignore[attr-defined]
        assert record.sampling_rate == 1.0  # type: ignore[attr-defined]

    def test_critical_stream_always_kept_at_zero_rate(self):
        f = TailSamplingFilter(default_rate=0.0, critical_streams=["Payment*", "Auth*"])
        record = _fake_access_record(status="ok", message_type="PaymentProcessed")
        assert f.filter(record) is True
        assert record.sampling_rule == "critical_stream"  # type: ignore[attr-defined]
        assert record.sampling_rate == 1.0  # type: ignore[attr-defined]

    def test_critical_stream_non_match_dropped_at_zero_rate(self):
        f = TailSamplingFilter(default_rate=0.0, critical_streams=["Payment*"])
        record = _fake_access_record(status="ok", message_type="OrderPlaced")
        assert f.filter(record) is False

    def test_random_sample_full_rate_keeps_everything(self):
        f = TailSamplingFilter(default_rate=1.0)
        record = _fake_access_record(status="ok", message_type="UpdateProfile")
        assert f.filter(record) is True
        assert record.sampling_rule == "random"  # type: ignore[attr-defined]
        assert record.sampling_rate == 1.0  # type: ignore[attr-defined]

    def test_random_sample_zero_rate_drops_happy_path(self):
        f = TailSamplingFilter(default_rate=0.0)
        record = _fake_access_record(status="ok", message_type="UpdateProfile")
        assert f.filter(record) is False

    def test_random_sample_applied_rate_shows_configured_rate(self):
        """When the random rule keeps a record, sampling_rate == default_rate."""
        f = TailSamplingFilter(default_rate=0.05)
        with patch("protean.utils.logging.random.random", return_value=0.0):
            record = _fake_access_record(status="ok", message_type="UpdateProfile")
            assert f.filter(record) is True
        assert record.sampling_rate == 0.05  # type: ignore[attr-defined]

    def test_always_keep_errors_disabled_allows_drop(self):
        """With ``always_keep_errors=False``, errors fall through to random."""
        f = TailSamplingFilter(default_rate=0.0, always_keep_errors=False)
        record = _fake_access_record(level=logging.ERROR, status="failed")
        assert f.filter(record) is False

    def test_always_keep_slow_disabled_allows_drop(self):
        f = TailSamplingFilter(default_rate=0.0, always_keep_slow=False)
        record = _fake_access_record(status="slow", level=logging.WARNING)
        assert f.filter(record) is False

    def test_non_access_logger_is_passthrough(self):
        """Records outside the protean.access namespace are never dropped."""
        f = TailSamplingFilter(default_rate=0.0)
        record = logging.LogRecord(
            name="protean.server.engine",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="engine started",
            args=(),
            exc_info=None,
        )
        assert f.filter(record) is True
        # No sampling metadata is added to non-access records.
        assert not hasattr(record, "sampling_decision")
        assert not hasattr(record, "sampling_rule")

    def test_nested_access_logger_namespace_is_sampled(self):
        """Sub-loggers like ``protean.access.http`` also flow through sampling."""
        f = TailSamplingFilter(default_rate=1.0)
        record = _fake_access_record(
            status="ok",
            message_type="GET /orders",
            name="protean.access.http",
        )
        assert f.filter(record) is True
        assert record.sampling_rule == "random"  # type: ignore[attr-defined]


class TestTailSamplingProcessor:
    """Structlog processor mirrors the filter behavior on event dicts."""

    def test_non_access_logger_passthrough(self):
        proc = TailSamplingProcessor(default_rate=0.0)
        event = {"logger": "protean.server.engine", "event": "started"}
        out = proc(None, "info", event)
        assert out is event
        assert "sampling_decision" not in out

    def test_error_event_kept(self):
        proc = TailSamplingProcessor(default_rate=0.0)
        event = {
            "logger": "protean.access",
            "level": "error",
            "status": "failed",
            "event": "access.handler_failed",
        }
        out = proc(None, "error", event)
        assert out["sampling_decision"] == "kept"
        assert out["sampling_rule"] == "error"
        assert out["sampling_rate"] == 1.0

    def test_slow_event_kept(self):
        proc = TailSamplingProcessor(default_rate=0.0)
        event = {"logger": "protean.access", "level": "warning", "status": "slow"}
        out = proc(None, "warning", event)
        assert out["sampling_rule"] == "slow"

    def test_critical_stream_kept(self):
        proc = TailSamplingProcessor(default_rate=0.0, critical_streams=["Payment*"])
        event = {
            "logger": "protean.access",
            "level": "info",
            "status": "ok",
            "message_type": "PaymentProcessed",
        }
        out = proc(None, "info", event)
        assert out["sampling_rule"] == "critical_stream"

    def test_critical_stream_configured_but_no_match_falls_through(self):
        """With patterns configured but no match, the rule falls through to
        random sampling — covers the `critical_streams present but miss` branch."""
        proc = TailSamplingProcessor(default_rate=0.0, critical_streams=["Payment*"])
        event = {
            "logger": "protean.access",
            "level": "info",
            "status": "ok",
            "message_type": "OrderPlaced",
        }
        with pytest.raises(structlog.DropEvent):
            proc(None, "info", event)

    def test_random_drop_raises_drop_event(self):
        proc = TailSamplingProcessor(default_rate=0.0)
        event = {
            "logger": "protean.access",
            "level": "info",
            "status": "ok",
            "message_type": "UpdateProfile",
        }
        with pytest.raises(structlog.DropEvent):
            proc(None, "info", event)

    def test_random_keep_at_full_rate(self):
        proc = TailSamplingProcessor(default_rate=1.0)
        event = {
            "logger": "protean.access",
            "level": "info",
            "status": "ok",
            "message_type": "UpdateProfile",
        }
        out = proc(None, "info", event)
        assert out["sampling_rule"] == "random"
        assert out["sampling_rate"] == 1.0

    def test_sub_logger_namespace_is_sampled(self):
        proc = TailSamplingProcessor(default_rate=0.0)
        event = {
            "logger": "protean.access.http",
            "level": "info",
            "status": "ok",
            "message_type": "GET /orders",
        }
        with pytest.raises(structlog.DropEvent):
            proc(None, "info", event)


class TestCriticalStreamGlobMatching:
    """``critical_streams`` uses fnmatch globs — verify through the filter."""

    def _keeps(self, patterns: list[str], message_type: str) -> bool:
        """Return True when the filter keeps a happy-path record (rate=0.0)
        exclusively because of a critical_streams match."""
        f = TailSamplingFilter(default_rate=0.0, critical_streams=patterns)
        record = _fake_access_record(status="ok", message_type=message_type)
        kept = f.filter(record)
        if not kept:
            return False
        return getattr(record, "sampling_rule", None) == "critical_stream"

    def test_prefix_wildcard_matches(self):
        assert self._keeps(["Pay*", "Auth*"], "PaymentProcessed")
        assert self._keeps(["Pay*", "Auth*"], "AuthLoginFailed")
        assert not self._keeps(["Pay*", "Auth*"], "OrderPlaced")

    def test_empty_message_type_never_matches(self):
        assert not self._keeps(["Pay*"], "")

    def test_empty_patterns_skip_the_rule(self):
        """No patterns → the filter falls through to random sampling, which
        drops at rate=0.0. Verifies no accidental match on empty pattern list."""
        assert not self._keeps([], "PaymentProcessed")

    def test_fnmatch_semantics_case_sensitive(self):
        """Critical stream matching is case-sensitive so accidental lookalikes
        (``pay`` vs ``PAY``) don't opt into retention."""
        assert self._keeps(["PAY"], "PAY")
        assert not self._keeps(["PAY"], "pay")


# ---------------------------------------------------------------------------
# End-to-end tests — the filter installed on protean.access samples real
# wide events emitted by command/event/query handlers.
# ---------------------------------------------------------------------------


class TestSamplingDisabledByDefault:
    """With no filter installed, every wide event emits."""

    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(Widget)
        test_domain.register(PlaceOrder, part_of=Widget)
        test_domain.register(SuccessHandler, part_of=Widget)
        test_domain.init(traverse=False)

    def test_all_events_emit_when_disabled(self, test_domain, caplog):
        count = 10
        with caplog.at_level(logging.DEBUG, logger="protean.access"):
            for _ in range(count):
                test_domain.process(PlaceOrder(widget_id=str(uuid4()), name="widget"))

        cmd_records = [
            r for r in _access_records(caplog) if getattr(r, "kind", "") == "command"
        ]
        assert len(cmd_records) == count
        for rec in cmd_records:
            assert not hasattr(rec, "sampling_decision")


class TestSamplingKeepsErrors:
    """Errors are kept at default_rate=0.0."""

    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain, install_sampling_filter):
        install_sampling_filter(default_rate=0.0)
        test_domain.register(Widget)
        test_domain.register(FailingCommand, part_of=Widget)
        test_domain.register(FailingHandler, part_of=Widget)
        test_domain.init(traverse=False)

    def test_error_wide_event_emitted(self, test_domain, caplog):
        with caplog.at_level(logging.DEBUG, logger="protean.access"):
            with pytest.raises(ValueError, match="boom"):
                test_domain.process(FailingCommand(widget_id=str(uuid4())))

        records = [
            r for r in _access_records(caplog) if getattr(r, "kind", "") == "command"
        ]
        assert len(records) == 1
        record = records[0]
        assert record.status == "failed"
        assert record.sampling_decision == "kept"  # type: ignore[attr-defined]
        assert record.sampling_rule == "error"  # type: ignore[attr-defined]
        assert record.sampling_rate == 1.0  # type: ignore[attr-defined]


class TestSamplingKeepsSlow:
    """Slow handlers are kept at default_rate=0.0."""

    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain, install_sampling_filter):
        install_sampling_filter(default_rate=0.0)
        test_domain.config["logging"]["slow_handler_threshold_ms"] = 10
        test_domain.register(Widget)
        test_domain.register(PlaceOrder, part_of=Widget)
        test_domain.register(SlowHandler, part_of=Widget)
        test_domain.init(traverse=False)

    def test_slow_wide_event_emitted(self, test_domain, caplog):
        with caplog.at_level(logging.DEBUG, logger="protean.access"):
            test_domain.process(PlaceOrder(widget_id=str(uuid4()), name="widget"))

        records = _access_records(caplog)
        slow = [r for r in records if getattr(r, "status", "") == "slow"]
        assert len(slow) >= 1
        record = slow[0]
        assert record.sampling_decision == "kept"  # type: ignore[attr-defined]
        assert record.sampling_rule == "slow"  # type: ignore[attr-defined]
        assert record.sampling_rate == 1.0  # type: ignore[attr-defined]


class TestSamplingKeepsCriticalStream:
    """Critical streams bypass the random sampler; non-match drops."""

    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain, install_sampling_filter):
        # message_type values carry the domain + version ("Test.PlaceOrder.v1").
        # The glob pattern spans that shape without locking to a specific version.
        install_sampling_filter(default_rate=0.0, critical_streams=["*.PlaceOrder.*"])
        test_domain.register(Widget)
        test_domain.register(PlaceOrder, part_of=Widget)
        test_domain.register(UpdateProfile, part_of=Widget)
        test_domain.register(SuccessHandler, part_of=Widget)
        test_domain.register(UpdateHandler, part_of=Widget)
        test_domain.init(traverse=False)

    def test_critical_stream_kept_non_match_dropped(self, test_domain, caplog):
        with caplog.at_level(logging.DEBUG, logger="protean.access"):
            test_domain.process(PlaceOrder(widget_id=str(uuid4()), name="widget"))
            test_domain.process(UpdateProfile(widget_id=str(uuid4()), name="widget"))

        cmd_records = [
            r for r in _access_records(caplog) if getattr(r, "kind", "") == "command"
        ]
        kept_types = {r.message_type: r for r in cmd_records}
        place_order_types = [t for t in kept_types if "PlaceOrder" in t]
        assert len(place_order_types) == 1, (
            f"expected PlaceOrder wide event to be kept, got {list(kept_types)}"
        )
        kept = kept_types[place_order_types[0]]
        assert kept.sampling_rule == "critical_stream"  # type: ignore[attr-defined]
        assert kept.sampling_rate == 1.0  # type: ignore[attr-defined]
        # UpdateProfile is not in critical_streams; at default_rate=0 it drops.
        update_types = [t for t in kept_types if "UpdateProfile" in t]
        assert update_types == []


class TestRandomSamplingRateExtremes:
    """default_rate=1.0 keeps everything; default_rate=0.0 drops happy path."""

    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(Widget)
        test_domain.register(PlaceOrder, part_of=Widget)
        test_domain.register(SuccessHandler, part_of=Widget)
        test_domain.init(traverse=False)

    def test_full_rate_keeps_everything(
        self, test_domain, caplog, install_sampling_filter
    ):
        install_sampling_filter(default_rate=1.0)
        count = 10
        with caplog.at_level(logging.DEBUG, logger="protean.access"):
            for _ in range(count):
                test_domain.process(PlaceOrder(widget_id=str(uuid4()), name="widget"))

        cmd_records = [
            r for r in _access_records(caplog) if getattr(r, "kind", "") == "command"
        ]
        assert len(cmd_records) == count
        for rec in cmd_records:
            assert rec.sampling_decision == "kept"  # type: ignore[attr-defined]
            assert rec.sampling_rule == "random"  # type: ignore[attr-defined]
            assert rec.sampling_rate == 1.0  # type: ignore[attr-defined]

    def test_zero_rate_drops_happy_path(
        self, test_domain, caplog, install_sampling_filter
    ):
        install_sampling_filter(default_rate=0.0)
        count = 10
        with caplog.at_level(logging.DEBUG, logger="protean.access"):
            for _ in range(count):
                test_domain.process(PlaceOrder(widget_id=str(uuid4()), name="widget"))

        cmd_records = [
            r for r in _access_records(caplog) if getattr(r, "kind", "") == "command"
        ]
        assert cmd_records == []


class TestRandomSamplingMetadata:
    """Kept random-sampled events carry the configured rate."""

    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain, install_sampling_filter):
        install_sampling_filter(default_rate=0.05)
        test_domain.register(Widget)
        test_domain.register(PlaceOrder, part_of=Widget)
        test_domain.register(SuccessHandler, part_of=Widget)
        test_domain.init(traverse=False)

    def test_random_kept_metadata(self, test_domain, caplog):
        """Force random.random() to always return 0.0 → always kept at the
        configured ``default_rate``."""
        with patch("protean.utils.logging.random.random", return_value=0.0):
            with caplog.at_level(logging.DEBUG, logger="protean.access"):
                test_domain.process(PlaceOrder(widget_id=str(uuid4()), name="widget"))

        records = [
            r for r in _access_records(caplog) if getattr(r, "kind", "") == "command"
        ]
        assert len(records) == 1
        record = records[0]
        assert record.sampling_decision == "kept"  # type: ignore[attr-defined]
        assert record.sampling_rule == "random"  # type: ignore[attr-defined]
        assert record.sampling_rate == 0.05  # type: ignore[attr-defined]


class TestNonAccessLoggersUnaffected:
    """Non-access logger records bypass the sampler entirely."""

    def test_non_access_logger_not_dropped(
        self, test_domain, caplog, install_sampling_filter
    ):
        install_sampling_filter(default_rate=0.0)
        logger = logging.getLogger("protean.server.engine")
        with caplog.at_level(logging.DEBUG, logger="protean.server.engine"):
            logger.info("engine.started")

        engine_records = [
            r for r in caplog.records if r.name == "protean.server.engine"
        ]
        assert len(engine_records) == 1
        assert not hasattr(engine_records[0], "sampling_decision")


# ---------------------------------------------------------------------------
# Wiring test: Domain.configure_logging() installs the filter via config
# ---------------------------------------------------------------------------


def _clear_root_logger() -> None:
    """Reset root logger state so configure_logging runs from a clean slate."""
    root = logging.getLogger()
    root.handlers.clear()
    root.filters.clear()
    root.setLevel(logging.WARNING)


def _clear_access_logger() -> None:
    """Remove any lingering TailSamplingFilter from protean.access."""
    access = logging.getLogger("protean.access")
    for f in list(access.filters):
        if isinstance(f, TailSamplingFilter):
            access.removeFilter(f)


@pytest.mark.no_test_domain
class TestDomainConfigureLoggingWiresSampling:
    """[logging.sampling] in domain.toml installs the filter on the access logger."""

    def setup_method(self) -> None:
        structlog.reset_defaults()
        _clear_root_logger()
        _clear_access_logger()

    def teardown_method(self) -> None:
        _clear_root_logger()
        _clear_access_logger()
        structlog.reset_defaults()

    def test_sampling_enabled_installs_filter(self):
        domain = Domain(
            root_path=str(Path(__file__).parent),
            name="TestSamplingEnabled",
            config={
                "logging": {
                    "sampling": {
                        "enabled": True,
                        "default_rate": 0.1,
                        "critical_streams": ["Payment*"],
                    }
                }
            },
        )
        domain.configure_logging()

        access = logging.getLogger("protean.access")
        installed = [f for f in access.filters if isinstance(f, TailSamplingFilter)]
        assert len(installed) == 1
        assert installed[0].default_rate == 0.1
        assert installed[0].critical_streams == ("Payment*",)

    def test_sampling_disabled_does_not_install_filter(self):
        domain = Domain(
            root_path=str(Path(__file__).parent),
            name="TestSamplingDisabled",
            config={"logging": {"sampling": {"enabled": False}}},
        )
        domain.configure_logging()

        access = logging.getLogger("protean.access")
        assert not any(isinstance(f, TailSamplingFilter) for f in access.filters)

    def test_repeated_configure_does_not_duplicate_filter(self):
        domain = Domain(
            root_path=str(Path(__file__).parent),
            name="TestSamplingIdempotent",
            config={"logging": {"sampling": {"enabled": True}}},
        )
        domain.configure_logging()
        domain.configure_logging()

        access = logging.getLogger("protean.access")
        installed = [f for f in access.filters if isinstance(f, TailSamplingFilter)]
        assert len(installed) == 1
