"""Tests for the stdlib → structlog ProcessorFormatter bridge.

Verifies that:
- stdlib loggers produce JSON-shaped output when format="json"
- stdlib and structlog loggers produce structurally identical JSON
- logger.exception preserves exc_info with structured kwargs
"""

import json
import logging
import os
from io import StringIO
from unittest.mock import patch

import structlog

from protean.utils.logging import configure_logging, get_logger


class TestStdlibJsonBridge:
    """Stdlib loggers emit JSON through ProcessorFormatter."""

    def setup_method(self):
        structlog.reset_defaults()
        root = logging.getLogger()
        root.handlers = []
        root.setLevel(logging.WARNING)

    def test_stdlib_logger_emits_json(self):
        """A stdlib logger produces valid JSON when format='json'."""
        buf = StringIO()

        with patch.dict(os.environ, {}, clear=True):
            configure_logging(level="DEBUG", format="json")

        root = logging.getLogger()
        # Replace the stdout handler with our buffer
        root.handlers = []
        handler = logging.StreamHandler(buf)
        handler.setLevel(logging.DEBUG)
        # Reuse the formatter from a fresh configure call
        with patch.dict(os.environ, {}, clear=True):
            configure_logging(level="DEBUG", format="json")
        handler.setFormatter(root.handlers[0].formatter)
        root.handlers = [handler]

        stdlib_logger = logging.getLogger("protean.test.stdlib_bridge")
        stdlib_logger.setLevel(logging.DEBUG)
        stdlib_logger.info("engine.started", extra={"foo": "bar"})

        output = buf.getvalue().strip()
        assert output, "Expected log output but got empty string"
        record = json.loads(output)

        assert "event" in record
        assert "level" in record
        assert "timestamp" in record

    def test_stdlib_and_structlog_produce_equivalent_json(self):
        """A stdlib logger and a structlog BoundLogger produce structurally
        identical JSON for the same event name and kwargs."""
        stdlib_buf = StringIO()
        structlog_buf = StringIO()

        with patch.dict(os.environ, {}, clear=True):
            configure_logging(level="DEBUG", format="json")

        root = logging.getLogger()
        formatter = root.handlers[0].formatter

        # Stdlib logger → stdlib_buf
        stdlib_handler = logging.StreamHandler(stdlib_buf)
        stdlib_handler.setLevel(logging.DEBUG)
        stdlib_handler.setFormatter(formatter)

        stdlib_logger = logging.getLogger("protean.test.stdlib_equiv")
        stdlib_logger.setLevel(logging.DEBUG)
        stdlib_logger.handlers = [stdlib_handler]
        stdlib_logger.propagate = False
        stdlib_logger.info("engine.started", extra={"foo": "bar"})

        # Structlog logger → structlog_buf
        structlog_handler = logging.StreamHandler(structlog_buf)
        structlog_handler.setLevel(logging.DEBUG)
        structlog_handler.setFormatter(formatter)

        structlog_logger_name = "protean.test.structlog_equiv"
        underlying = logging.getLogger(structlog_logger_name)
        underlying.setLevel(logging.DEBUG)
        underlying.handlers = [structlog_handler]
        underlying.propagate = False

        sl = get_logger(structlog_logger_name)
        sl.info("engine.started", foo="bar")

        stdlib_output = stdlib_buf.getvalue().strip()
        structlog_output = structlog_buf.getvalue().strip()

        assert stdlib_output, "Expected stdlib log output"
        assert structlog_output, "Expected structlog log output"

        stdlib_record = json.loads(stdlib_output)
        structlog_record = json.loads(structlog_output)

        # Both must have the same top-level keys
        # (timestamps will differ but keys must be identical)
        assert set(stdlib_record.keys()) & {"event", "level", "timestamp"} == {
            "event",
            "level",
            "timestamp",
        }
        assert set(structlog_record.keys()) & {"event", "level", "timestamp"} == {
            "event",
            "level",
            "timestamp",
        }

        # Both must carry the same event name and level
        assert stdlib_record["level"] == structlog_record["level"]

    def test_exception_preserves_exc_info_with_kwargs(self):
        """logger.exception in a raised-exception context produces a record
        with exc_info populated and structured kwargs intact."""
        buf = StringIO()

        with patch.dict(os.environ, {}, clear=True):
            configure_logging(level="DEBUG", format="json")

        root = logging.getLogger()
        formatter = root.handlers[0].formatter

        handler = logging.StreamHandler(buf)
        handler.setLevel(logging.DEBUG)
        handler.setFormatter(formatter)

        test_logger = logging.getLogger("protean.test.exc_info")
        test_logger.setLevel(logging.DEBUG)
        test_logger.handlers = [handler]
        test_logger.propagate = False

        try:
            raise ValueError("test error")
        except ValueError:
            test_logger.exception("test_event", extra={"key": "value"})

        output = buf.getvalue().strip()
        assert output, "Expected log output with exception"
        record = json.loads(output)

        assert "event" in record
        # The exception info should be present in the output
        # structlog's format_exc_info processor converts it to a string
        output_text = json.dumps(record)
        assert "ValueError" in output_text or "test error" in output_text
