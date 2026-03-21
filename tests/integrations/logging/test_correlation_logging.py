"""Tests for automatic correlation context injection into log records.

Verifies that:
- ``ProteanCorrelationFilter`` adds ``correlation_id`` and ``causation_id``
  to stdlib ``LogRecord`` objects when a domain context is active.
- ``protean_correlation_processor`` adds the same fields to structlog
  event dicts.
- Both integrations are safe no-ops when no domain context is active.
- ``domain.configure_logging()`` wires up both the filter and processor.
"""

import logging

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.command import BaseCommand
from protean.core.command_handler import BaseCommandHandler
from protean.fields import Identifier, String
from protean.integrations.logging import (
    ProteanCorrelationFilter,
    protean_correlation_processor,
)
from protean.utils.eventing import (
    DomainMeta,
    Message,
    MessageHeaders,
    Metadata,
)
from protean.utils.globals import g
from protean.utils.mixins import handle


# ---------------------------------------------------------------------------
# Domain elements for integration tests
# ---------------------------------------------------------------------------


class Widget(BaseAggregate):
    widget_id = Identifier(identifier=True)
    name = String(required=True)


class CreateWidget(BaseCommand):
    widget_id = Identifier(identifier=True)
    name = String(required=True)


# Storage for values captured inside handlers
_captured: dict = {}


class WidgetCommandHandler(BaseCommandHandler):
    @handle(CreateWidget)
    def create(self, command: CreateWidget) -> None:
        # Capture the correlation context visible via the filter during handling
        filt = ProteanCorrelationFilter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="inside handler",
            args=(),
            exc_info=None,
        )
        filt.filter(record)
        _captured["cmd_correlation_id"] = record.correlation_id  # type: ignore[attr-defined]
        _captured["cmd_causation_id"] = record.causation_id  # type: ignore[attr-defined]

        widget = Widget(widget_id=command.widget_id, name=command.name)
        from protean.utils.globals import current_domain

        current_domain.repository_for(Widget).add(widget)


# ---------------------------------------------------------------------------
# ProteanCorrelationFilter -- no context
# ---------------------------------------------------------------------------


class TestCorrelationFilterNoContext:
    """Filter behaviour when no domain context or message context exists."""

    @pytest.mark.no_test_domain
    def test_no_domain_context(self):
        """Fields default to empty string when no domain context is active."""
        filt = ProteanCorrelationFilter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="hello",
            args=(),
            exc_info=None,
        )
        result = filt.filter(record)

        assert result is True
        assert record.correlation_id == ""  # type: ignore[attr-defined]
        assert record.causation_id == ""  # type: ignore[attr-defined]

    def test_no_message_in_context(self, test_domain):
        """Fields default to empty string when g.message_in_context is not set."""
        filt = ProteanCorrelationFilter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="hello",
            args=(),
            exc_info=None,
        )
        # Ensure no message_in_context
        g.pop("message_in_context", None)

        result = filt.filter(record)

        assert result is True
        assert record.correlation_id == ""  # type: ignore[attr-defined]
        assert record.causation_id == ""  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# ProteanCorrelationFilter -- with context
# ---------------------------------------------------------------------------


class TestCorrelationFilterWithContext:
    """Filter behaviour when a domain context with a message is active."""

    def test_extracts_correlation_and_causation(self, test_domain):
        """Filter reads correlation_id and causation_id from g.message_in_context."""
        msg = Message(
            data={"widget_id": "w-1", "name": "Sprocket"},
            metadata=Metadata(
                headers=MessageHeaders(id="msg-001", type="Test.CreateWidget.v1"),
                domain=DomainMeta(
                    kind="COMMAND",
                    correlation_id="corr-abc",
                    causation_id="cause-xyz",
                ),
            ),
        )
        g.message_in_context = msg

        filt = ProteanCorrelationFilter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="processing",
            args=(),
            exc_info=None,
        )
        result = filt.filter(record)

        assert result is True
        assert record.correlation_id == "corr-abc"  # type: ignore[attr-defined]
        assert record.causation_id == "cause-xyz"  # type: ignore[attr-defined]

        g.pop("message_in_context", None)

    def test_none_causation_becomes_empty_string(self, test_domain):
        """When causation_id is None (root command), it is set to empty string."""
        msg = Message(
            data={},
            metadata=Metadata(
                headers=MessageHeaders(id="msg-002", type="Test.Foo.v1"),
                domain=DomainMeta(
                    kind="COMMAND",
                    correlation_id="corr-123",
                    causation_id=None,
                ),
            ),
        )
        g.message_in_context = msg

        filt = ProteanCorrelationFilter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="root command",
            args=(),
            exc_info=None,
        )
        filt.filter(record)

        assert record.correlation_id == "corr-123"  # type: ignore[attr-defined]
        assert record.causation_id == ""  # type: ignore[attr-defined]

        g.pop("message_in_context", None)

    def test_message_without_domain_meta(self, test_domain):
        """When message has metadata but no domain meta, fields are empty."""
        msg = Message(
            data={},
            metadata=Metadata(
                headers=MessageHeaders(id="msg-003", type="Test.Bar.v1"),
                domain=None,
            ),
        )
        g.message_in_context = msg

        filt = ProteanCorrelationFilter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="no domain meta",
            args=(),
            exc_info=None,
        )
        filt.filter(record)

        assert record.correlation_id == ""  # type: ignore[attr-defined]
        assert record.causation_id == ""  # type: ignore[attr-defined]

        g.pop("message_in_context", None)


# ---------------------------------------------------------------------------
# structlog processor -- no context
# ---------------------------------------------------------------------------


class TestStructlogProcessorNoContext:
    """Processor behaviour when no domain context is active."""

    @pytest.mark.no_test_domain
    def test_no_domain_context(self):
        """Fields default to empty string when no domain context is active."""
        event_dict: dict = {"event": "hello"}
        result = protean_correlation_processor(None, "info", event_dict)

        assert result["correlation_id"] == ""
        assert result["causation_id"] == ""

    def test_no_message_in_context(self, test_domain):
        """Fields default to empty string when g.message_in_context is not set."""
        g.pop("message_in_context", None)

        event_dict: dict = {"event": "hello"}
        result = protean_correlation_processor(None, "info", event_dict)

        assert result["correlation_id"] == ""
        assert result["causation_id"] == ""


# ---------------------------------------------------------------------------
# structlog processor -- with context
# ---------------------------------------------------------------------------


class TestStructlogProcessorWithContext:
    """Processor behaviour when a domain context with a message is active."""

    def test_extracts_correlation_and_causation(self, test_domain):
        """Processor reads correlation_id and causation_id from g.message_in_context."""
        msg = Message(
            data={},
            metadata=Metadata(
                headers=MessageHeaders(id="msg-010", type="Test.Cmd.v1"),
                domain=DomainMeta(
                    kind="COMMAND",
                    correlation_id="struct-corr-1",
                    causation_id="struct-cause-1",
                ),
            ),
        )
        g.message_in_context = msg

        event_dict: dict = {"event": "working"}
        result = protean_correlation_processor(None, "info", event_dict)

        assert result["correlation_id"] == "struct-corr-1"
        assert result["causation_id"] == "struct-cause-1"
        # Original event key preserved
        assert result["event"] == "working"

        g.pop("message_in_context", None)

    def test_none_causation_becomes_empty_string(self, test_domain):
        """When causation_id is None (root command), it is set to empty string."""
        msg = Message(
            data={},
            metadata=Metadata(
                headers=MessageHeaders(id="msg-011", type="Test.Cmd.v1"),
                domain=DomainMeta(
                    kind="COMMAND",
                    correlation_id="struct-corr-2",
                    causation_id=None,
                ),
            ),
        )
        g.message_in_context = msg

        event_dict: dict = {"event": "root"}
        result = protean_correlation_processor(None, "info", event_dict)

        assert result["correlation_id"] == "struct-corr-2"
        assert result["causation_id"] == ""

        g.pop("message_in_context", None)


# ---------------------------------------------------------------------------
# domain.configure_logging()
# ---------------------------------------------------------------------------


class TestDomainConfigureLogging:
    """Test the Domain.configure_logging() convenience method."""

    def test_adds_filter_to_root_logger(self, test_domain):
        """configure_logging() attaches ProteanCorrelationFilter to root logger."""
        root = logging.getLogger()
        # Remove any pre-existing correlation filters
        root.filters = [
            f for f in root.filters if not isinstance(f, ProteanCorrelationFilter)
        ]
        assert not any(isinstance(f, ProteanCorrelationFilter) for f in root.filters)

        test_domain.configure_logging(level="WARNING")

        assert any(isinstance(f, ProteanCorrelationFilter) for f in root.filters)

    def test_idempotent_on_repeated_calls(self, test_domain):
        """Calling configure_logging() twice does not add duplicate filters."""
        root = logging.getLogger()
        root.filters = [
            f for f in root.filters if not isinstance(f, ProteanCorrelationFilter)
        ]

        test_domain.configure_logging(level="WARNING")
        test_domain.configure_logging(level="WARNING")

        correlation_filters = [
            f for f in root.filters if isinstance(f, ProteanCorrelationFilter)
        ]
        assert len(correlation_filters) == 1

    def test_forwards_kwargs_to_configure_logging(self, test_domain):
        """Keyword arguments are forwarded to utils.logging.configure_logging."""
        # If level is accepted, it should take effect
        test_domain.configure_logging(level="ERROR")
        root = logging.getLogger()
        assert root.level == logging.ERROR


# ---------------------------------------------------------------------------
# End-to-end: correlation context in logs during command processing
# ---------------------------------------------------------------------------


class TestEndToEndCorrelationInLogs:
    """Verify correlation IDs flow through to log records during real processing."""

    def test_correlation_id_visible_during_command_handling(self, test_domain):
        """Log records inside a command handler see the command's correlation_id."""
        test_domain.register(Widget)
        test_domain.register(CreateWidget, part_of=Widget)
        test_domain.register(WidgetCommandHandler, part_of=Widget)
        test_domain.init(traverse=False)

        _captured.clear()

        test_domain.process(
            CreateWidget(widget_id="w-100", name="Gizmo"),
            asynchronous=False,
            correlation_id="e2e-corr-id",
        )

        # The command handler captures correlation context via the filter
        assert _captured["cmd_correlation_id"] == "e2e-corr-id"

    def test_auto_generated_correlation_id_visible(self, test_domain):
        """When no explicit correlation_id is given, the auto-generated one is visible."""
        test_domain.register(Widget)
        test_domain.register(CreateWidget, part_of=Widget)
        test_domain.register(WidgetCommandHandler, part_of=Widget)
        test_domain.init(traverse=False)

        _captured.clear()

        test_domain.process(
            CreateWidget(widget_id="w-300", name="Gadget"),
            asynchronous=False,
        )

        # An auto-generated correlation_id should still be visible
        assert _captured["cmd_correlation_id"] != ""
        assert len(_captured["cmd_correlation_id"]) > 0


# ---------------------------------------------------------------------------
# Filter works with stdlib formatter using %(correlation_id)s
# ---------------------------------------------------------------------------


class TestFilterWithFormatter:
    """Verify the filter works with stdlib formatters that reference the fields."""

    def test_formatter_can_reference_correlation_id(self, test_domain):
        """A formatter using %(correlation_id)s works when filter is active."""
        msg = Message(
            data={},
            metadata=Metadata(
                headers=MessageHeaders(id="msg-fmt", type="Test.Fmt.v1"),
                domain=DomainMeta(
                    kind="COMMAND",
                    correlation_id="fmt-corr",
                    causation_id="fmt-cause",
                ),
            ),
        )
        g.message_in_context = msg

        formatter = logging.Formatter(
            "%(message)s | corr=%(correlation_id)s | cause=%(causation_id)s"
        )
        filt = ProteanCorrelationFilter()

        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="formatted",
            args=(),
            exc_info=None,
        )
        filt.filter(record)
        output = formatter.format(record)

        assert "corr=fmt-corr" in output
        assert "cause=fmt-cause" in output

        g.pop("message_in_context", None)

    @pytest.mark.no_test_domain
    def test_formatter_safe_without_context(self):
        """A formatter using %(correlation_id)s works even without context."""
        formatter = logging.Formatter(
            "%(message)s | corr=%(correlation_id)s | cause=%(causation_id)s"
        )
        filt = ProteanCorrelationFilter()

        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="no context",
            args=(),
            exc_info=None,
        )
        filt.filter(record)
        output = formatter.format(record)

        assert "corr=" in output
        assert "cause=" in output
        # No KeyError raised
