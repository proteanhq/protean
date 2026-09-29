"""Protean's logging filters run for records from child loggers.

A filter on a logger runs only for records logged on that logger. Records
from ``logging.getLogger("ordering.x")`` propagate to the root logger's
handlers without passing the root logger's own filters. Protean therefore
attaches its correlation, OTel and redaction filters to each root handler as
well as to the root logger.
"""

import logging
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from protean.domain import Domain
from protean.integrations.logging import (
    OTelTraceContextFilter,
    ProteanCorrelationFilter,
    ProteanRedactionFilter,
)
from protean.utils.eventing import DomainMeta, Message, MessageHeaders, Metadata
from protean.utils.globals import g
from protean.utils.logging import _install_root_filter, configure_logging

CHILD_LOGGER = "ordering.x"


class _Recorder(logging.Handler):
    """Keeps every record it emits."""

    def __init__(self, records: list[logging.LogRecord]) -> None:
        super().__init__(level=logging.DEBUG)
        self.records = records

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


def _dict_config(records: list[logging.LogRecord]) -> dict[str, Any]:
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "handlers": {"rec": {"()": lambda: _Recorder(records)}},
        "root": {"handlers": ["rec"], "level": "DEBUG"},
    }


def _record_root_handler(records: list[logging.LogRecord]) -> None:
    """Keep what the installed console handler emits, filters applied first."""
    handlers = logging.getLogger().handlers
    assert handlers
    console = handlers[0]
    console.emit = records.append  # type: ignore[method-assign]


def _log_on_child(**extra: Any) -> None:
    child = logging.getLogger(CHILD_LOGGER)
    child.setLevel(logging.DEBUG)
    child.info("hello", extra=extra or None)


def _set_message_context() -> None:
    g.message_in_context = Message(
        data={},
        metadata=Metadata(
            headers=MessageHeaders(id="msg-1", type="Test.Thing.v1"),
            domain=DomainMeta(kind="COMMAND", correlation_id="c-1", causation_id="k-1"),
        ),
    )


def _count(target: logging.Filterer, cls: type) -> int:
    return sum(isinstance(f, cls) for f in target.filters)


@pytest.fixture
def telemetry_domain() -> Domain:
    return Domain(
        root_path=str(Path(__file__).parent),
        name="RootFilterOTel",
        config={"telemetry": {"enabled": True}},
    )


class TestInstallRootFilter:
    def test_adds_to_root_and_each_handler(self):
        root = logging.getLogger()
        root.filters = []
        first, second = _Recorder([]), _Recorder([])
        root.handlers = [first, second]

        _install_root_filter(ProteanCorrelationFilter())

        assert _count(root, ProteanCorrelationFilter) == 1
        assert _count(first, ProteanCorrelationFilter) == 1
        assert _count(second, ProteanCorrelationFilter) == 1

    def test_skips_target_that_already_has_the_class(self):
        root = logging.getLogger()
        handler = _Recorder([])
        existing = ProteanCorrelationFilter()
        root.filters = [existing]
        handler.addFilter(existing)
        root.handlers = [handler]

        _install_root_filter(ProteanCorrelationFilter())

        assert root.filters == [existing]
        assert handler.filters == [existing]

    def test_adds_to_handler_lacking_it_when_root_has_it(self):
        root = logging.getLogger()
        existing = ProteanCorrelationFilter()
        root.filters = [existing]
        handler = _Recorder([])
        root.handlers = [handler]

        _install_root_filter(ProteanCorrelationFilter())

        assert root.filters == [existing]
        assert _count(handler, ProteanCorrelationFilter) == 1

    def test_without_handlers_only_root_gets_it(self):
        root = logging.getLogger()
        root.filters = []
        root.handlers = []

        _install_root_filter(ProteanCorrelationFilter())

        assert _count(root, ProteanCorrelationFilter) == 1
        assert root.handlers == []


class TestCorrelationOnChildLoggerRecords:
    def test_dict_config_path(self, test_domain):
        records: list[logging.LogRecord] = []
        test_domain.configure_logging(dict_config=_dict_config(records))
        _set_message_context()
        try:
            _log_on_child()
        finally:
            g.pop("message_in_context", None)

        assert records
        assert records[-1].correlation_id == "c-1"  # type: ignore[attr-defined]
        assert records[-1].causation_id == "k-1"  # type: ignore[attr-defined]

    def test_default_path(self, test_domain):
        records: list[logging.LogRecord] = []
        test_domain.configure_logging(level="DEBUG", format="json")
        _record_root_handler(records)
        _set_message_context()
        try:
            _log_on_child()
        finally:
            g.pop("message_in_context", None)

        assert records
        assert records[-1].correlation_id == "c-1"  # type: ignore[attr-defined]
        assert records[-1].causation_id == "k-1"  # type: ignore[attr-defined]

    def test_outside_any_context_sets_empty_ids(self):
        records: list[logging.LogRecord] = []
        with patch.dict("os.environ", {}, clear=True):
            configure_logging(dict_config=_dict_config(records))
        _log_on_child()

        assert records
        assert records[-1].correlation_id == ""  # type: ignore[attr-defined]
        assert records[-1].causation_id == ""  # type: ignore[attr-defined]


class TestRedactionOnChildLoggerRecords:
    def test_domain_entry(self, test_domain):
        test_domain.config["logging"] = {"redact": ["password"]}
        records: list[logging.LogRecord] = []
        test_domain.configure_logging(level="DEBUG", format="json")
        _record_root_handler(records)
        _log_on_child(password="s3cret")

        assert records
        assert records[-1].password == "[REDACTED]"  # type: ignore[attr-defined]

    def test_util_entry_default_path(self):
        records: list[logging.LogRecord] = []
        with patch.dict("os.environ", {}, clear=True):
            configure_logging(level="DEBUG", format="json", redact=["password"])
        _record_root_handler(records)
        _log_on_child(password="s3cret")

        assert records
        assert records[-1].password == "[REDACTED]"  # type: ignore[attr-defined]

    def test_util_entry_dict_config_path(self):
        records: list[logging.LogRecord] = []
        with patch.dict("os.environ", {}, clear=True):
            configure_logging(dict_config=_dict_config(records), redact=["password"])
        _log_on_child(password="s3cret")

        assert records
        assert records[-1].password == "[REDACTED]"  # type: ignore[attr-defined]

    def test_no_redaction_filter_on_handlers_without_redact(self):
        records: list[logging.LogRecord] = []
        with patch.dict("os.environ", {}, clear=True):
            configure_logging(dict_config=_dict_config(records))
        _log_on_child(password="s3cret")

        assert records
        assert records[-1].password == "s3cret"  # type: ignore[attr-defined]
        for handler in logging.getLogger().handlers:
            assert _count(handler, ProteanRedactionFilter) == 0


class TestOTelOnChildLoggerRecords:
    def test_telemetry_enabled_adds_trace_fields(self, telemetry_domain):
        telemetry_domain.configure_logging(level="DEBUG", format="json")
        records: list[logging.LogRecord] = []
        _record_root_handler(records)
        _log_on_child()

        assert records
        assert records[-1].trace_id == ""  # type: ignore[attr-defined]
        assert records[-1].span_id == ""  # type: ignore[attr-defined]
        assert records[-1].trace_flags == 0  # type: ignore[attr-defined]

    def test_telemetry_disabled_installs_no_otel_filter(self, test_domain):
        test_domain.configure_logging(level="DEBUG", format="json")

        root = logging.getLogger()
        assert root.handlers
        assert _count(root, OTelTraceContextFilter) == 0
        for handler in root.handlers:
            assert _count(handler, OTelTraceContextFilter) == 0


class TestRepeatedConfigure:
    def test_default_path_twice(self, telemetry_domain):
        telemetry_domain.config["logging"] = {"redact": ["password"]}
        telemetry_domain.configure_logging(level="DEBUG", format="json")
        telemetry_domain.configure_logging(level="DEBUG", format="json")

        root = logging.getLogger()
        assert root.handlers
        for target in [root, *root.handlers]:
            assert _count(target, ProteanCorrelationFilter) == 1
            assert _count(target, OTelTraceContextFilter) == 1
            assert _count(target, ProteanRedactionFilter) == 1

    def test_dict_config_path_twice(self, test_domain):
        records: list[logging.LogRecord] = []
        config = _dict_config(records)
        test_domain.configure_logging(dict_config=config, redact=["password"])
        test_domain.configure_logging(dict_config=config, redact=["password"])

        root = logging.getLogger()
        assert root.handlers
        for target in [root, *root.handlers]:
            assert _count(target, ProteanCorrelationFilter) == 1
            assert _count(target, ProteanRedactionFilter) == 1
