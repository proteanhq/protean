"""Protean's logging filters run for records from child loggers.

A filter on a logger runs only for records logged on that logger. Records
from ``logging.getLogger("ordering.x")`` propagate to the root logger's
handlers without passing the root logger's own filters. Protean therefore
attaches its correlation, OTel and redaction filters to each root handler as
well as to the root logger.
"""

import logging
import logging.handlers
import queue
from typing import Any
from unittest.mock import patch

import pytest
from opentelemetry.sdk.trace import TracerProvider as SDKTracerProvider

from protean.domain import Domain
from protean.integrations.logging import (
    OTelTraceContextFilter,
    ProteanCorrelationFilter,
    ProteanRedactionFilter,
)
from protean.server.supervisor import _build_queue_listener, _install_worker_log_queue
from protean.utils.eventing import DomainMeta, Message, MessageHeaders, Metadata
from protean.utils.globals import g
from protean.utils.logging import (
    _install_root_filter,
    _move_redaction_filter_last,
    configure_logging,
)

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
def telemetry_domain(test_domain: Domain) -> Domain:
    test_domain.config["telemetry"] = {"enabled": True}
    return test_domain


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

    @pytest.mark.no_test_domain
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
        tracer = SDKTracerProvider().get_tracer("test")
        with tracer.start_as_current_span("child-log") as span:
            _log_on_child()
        context = span.get_span_context()

        assert records
        assert records[-1].trace_id == f"{context.trace_id:032x}"  # type: ignore[attr-defined]
        assert records[-1].span_id == f"{context.span_id:016x}"  # type: ignore[attr-defined]
        assert records[-1].trace_flags == int(context.trace_flags)  # type: ignore[attr-defined]

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

    def test_dict_config_path_twice(self, telemetry_domain):
        records: list[logging.LogRecord] = []
        config = _dict_config(records)
        telemetry_domain.configure_logging(dict_config=config, redact=["password"])
        telemetry_domain.configure_logging(dict_config=config, redact=["password"])

        root = logging.getLogger()
        assert root.handlers
        for target in [root, *root.handlers]:
            assert _count(target, ProteanCorrelationFilter) == 1
            assert _count(target, OTelTraceContextFilter) == 1
            assert _count(target, ProteanRedactionFilter) == 1

        _log_on_child(password="s3cret")

        assert records
        assert records[-1].password == "[REDACTED]"  # type: ignore[attr-defined]


class TestMultiWorkerQueuePath:
    """Worker records keep their ids and masking through the supervisor's queue."""

    def test_worker_queue_handler_gets_the_protean_filters(self, test_domain):
        test_domain.config["logging"] = {"redact": ["password"]}
        test_domain.configure_logging(level="DEBUG", format="json")
        user_filter = logging.Filter("only-this")
        logging.getLogger().addFilter(user_filter)
        log_queue: queue.Queue[logging.LogRecord] = queue.Queue()

        _install_worker_log_queue(log_queue)  # type: ignore[arg-type]

        handlers = logging.getLogger().handlers
        assert len(handlers) == 1
        queue_handler = handlers[0]
        assert isinstance(queue_handler, logging.handlers.QueueHandler)
        assert _count(queue_handler, ProteanCorrelationFilter) == 1
        assert _count(queue_handler, ProteanRedactionFilter) == 1
        assert user_filter not in queue_handler.filters

    def test_worker_child_record_carries_ids_and_masking(self, test_domain):
        test_domain.config["logging"] = {"redact": ["password"]}
        test_domain.configure_logging(level="DEBUG", format="json")
        log_queue: queue.Queue[logging.LogRecord] = queue.Queue()
        _install_worker_log_queue(log_queue)  # type: ignore[arg-type]

        _set_message_context()
        try:
            _log_on_child(password="s3cret")
        finally:
            g.pop("message_in_context", None)

        record = log_queue.get_nowait()
        assert record.correlation_id == "c-1"  # type: ignore[attr-defined]
        assert record.causation_id == "k-1"  # type: ignore[attr-defined]
        assert record.password == "[REDACTED]"  # type: ignore[attr-defined]

    def test_listener_keeps_the_ids_a_worker_set(self, test_domain):
        test_domain.configure_logging(level="DEBUG", format="json")
        records: list[logging.LogRecord] = []
        _record_root_handler(records)
        log_queue: queue.Queue[logging.LogRecord] = queue.Queue()
        record = logging.LogRecord(
            CHILD_LOGGER, logging.INFO, __file__, 1, "from worker", None, None
        )
        record.correlation_id = "c-worker"
        record.causation_id = "k-worker"

        listener = _build_queue_listener(log_queue)  # type: ignore[arg-type]
        listener.start()
        log_queue.put(record)
        listener.stop()

        assert records
        assert records[-1].correlation_id == "c-worker"  # type: ignore[attr-defined]
        assert records[-1].causation_id == "k-worker"  # type: ignore[attr-defined]

    def test_listener_still_runs_other_handler_filters(self, test_domain):
        test_domain.configure_logging(level="DEBUG", format="json")
        records: list[logging.LogRecord] = []
        _record_root_handler(records)
        logging.getLogger().handlers[0].addFilter(logging.Filter("elsewhere"))
        log_queue: queue.Queue[logging.LogRecord] = queue.Queue()
        record = logging.LogRecord(
            CHILD_LOGGER, logging.INFO, __file__, 1, "from worker", None, None
        )

        listener = _build_queue_listener(log_queue)  # type: ignore[arg-type]
        listener.start()
        log_queue.put(record)
        listener.stop()

        assert records == []

    def test_listener_respects_handler_level(self, test_domain):
        test_domain.configure_logging(level="DEBUG", format="json")
        records: list[logging.LogRecord] = []
        _record_root_handler(records)
        logging.getLogger().handlers[0].setLevel(logging.ERROR)
        log_queue: queue.Queue[logging.LogRecord] = queue.Queue()
        record = logging.LogRecord(
            CHILD_LOGGER, logging.INFO, __file__, 1, "from worker", None, None
        )

        listener = _build_queue_listener(log_queue)  # type: ignore[arg-type]
        listener.start()
        log_queue.put(record)
        listener.stop()

        assert records == []

    def test_listener_calls_handler_handle(self, test_domain):
        test_domain.configure_logging(level="DEBUG", format="json")
        handled: list[logging.LogRecord] = []

        class _Overriding(_Recorder):
            def handle(self, record: logging.LogRecord) -> bool:
                handled.append(record)
                return super().handle(record)

        root = logging.getLogger()
        custom = _Overriding([])
        root.addHandler(custom)
        _install_root_filter(ProteanCorrelationFilter())
        log_queue: queue.Queue[logging.LogRecord] = queue.Queue()
        record = logging.LogRecord(
            CHILD_LOGGER, logging.INFO, __file__, 1, "from worker", None, None
        )
        record.correlation_id = "c-worker"
        record.causation_id = "k-worker"

        listener = _build_queue_listener(log_queue)  # type: ignore[arg-type]
        listener.start()
        log_queue.put(record)
        listener.stop()

        assert len(handled) == 1
        assert custom.records[-1].correlation_id == "c-worker"  # type: ignore[attr-defined]

    def test_listener_keeps_the_trace_ids_a_worker_set(self, telemetry_domain):
        telemetry_domain.configure_logging(level="DEBUG", format="json")
        records: list[logging.LogRecord] = []
        _record_root_handler(records)
        log_queue: queue.Queue[logging.LogRecord] = queue.Queue()
        record = logging.LogRecord(
            CHILD_LOGGER, logging.INFO, __file__, 1, "from worker", None, None
        )
        record.correlation_id = "c-worker"
        record.causation_id = "k-worker"
        record.trace_id = "t-worker"
        record.span_id = "s-worker"
        record.trace_flags = 1

        listener = _build_queue_listener(log_queue)  # type: ignore[arg-type]
        listener.start()
        log_queue.put(record)
        listener.stop()

        assert records
        assert records[-1].trace_id == "t-worker"  # type: ignore[attr-defined]
        assert records[-1].span_id == "s-worker"  # type: ignore[attr-defined]
        assert records[-1].trace_flags == 1  # type: ignore[attr-defined]

    def test_listener_fills_ids_on_a_record_without_them(self, telemetry_domain):
        telemetry_domain.configure_logging(level="DEBUG", format="json")
        records: list[logging.LogRecord] = []
        _record_root_handler(records)
        log_queue: queue.Queue[logging.LogRecord] = queue.Queue()
        record = logging.LogRecord(
            CHILD_LOGGER, logging.INFO, __file__, 1, "from worker", None, None
        )

        listener = _build_queue_listener(log_queue)  # type: ignore[arg-type]
        listener.start()
        log_queue.put(record)
        listener.stop()

        assert records
        assert records[-1].correlation_id == ""  # type: ignore[attr-defined]
        assert records[-1].causation_id == ""  # type: ignore[attr-defined]
        assert records[-1].trace_id == ""  # type: ignore[attr-defined]
        assert records[-1].span_id == ""  # type: ignore[attr-defined]
        assert records[-1].trace_flags == 0  # type: ignore[attr-defined]

    def _queued_child_record(
        self, domain: Domain, log_queue: "queue.Queue[logging.LogRecord]"
    ) -> logging.LogRecord:
        with domain.domain_context():
            g.correlation_id = "secret-corr-123"
            g.causation_id = "secret-caus-456"
            _log_on_child()
        return log_queue.get_nowait()

    def test_two_dict_config_calls_mask_both_keys(self, test_domain):
        test_domain.config["telemetry"] = {"enabled": False}
        test_domain.config["logging"] = {}
        config = _dict_config([])
        test_domain.configure_logging(dict_config=config, redact=["correlation_id"])
        test_domain.configure_logging(dict_config=config, redact=["causation_id"])
        log_queue: queue.Queue[logging.LogRecord] = queue.Queue()

        _install_worker_log_queue(log_queue)  # type: ignore[arg-type]

        queue_handler = logging.getLogger().handlers[0]
        assert _count(queue_handler, ProteanRedactionFilter) == 2
        _assert_redaction_runs_last()
        record = self._queued_child_record(test_domain, log_queue)
        assert record.correlation_id == "[REDACTED]"  # type: ignore[attr-defined]
        assert record.causation_id == "[REDACTED]"  # type: ignore[attr-defined]

    def test_two_redaction_filters_declared_on_root_mask_both_keys(self, test_domain):
        test_domain.config["telemetry"] = {"enabled": False}
        test_domain.config["logging"] = {}
        config = _dict_config([])
        config["filters"] = {
            "red_corr": {"()": lambda: ProteanRedactionFilter(["correlation_id"])},
            "red_caus": {"()": lambda: ProteanRedactionFilter(["causation_id"])},
        }
        config["root"]["filters"] = ["red_corr", "red_caus"]
        test_domain.configure_logging(dict_config=config)
        log_queue: queue.Queue[logging.LogRecord] = queue.Queue()

        _install_worker_log_queue(log_queue)  # type: ignore[arg-type]

        queue_handler = logging.getLogger().handlers[0]
        assert _count(queue_handler, ProteanRedactionFilter) == 2
        _assert_redaction_runs_last()
        record = self._queued_child_record(test_domain, log_queue)
        assert record.correlation_id == "[REDACTED]"  # type: ignore[attr-defined]
        assert record.causation_id == "[REDACTED]"  # type: ignore[attr-defined]

    def test_two_default_path_calls_mask_both_keys(self, test_domain):
        test_domain.config["telemetry"] = {"enabled": False}
        test_domain.config["logging"] = {"redact": ["correlation_id"]}
        test_domain.configure_logging(level="DEBUG", format="json")
        test_domain.config["logging"] = {"redact": ["causation_id"]}
        test_domain.configure_logging(level="DEBUG", format="json")
        log_queue: queue.Queue[logging.LogRecord] = queue.Queue()

        _install_worker_log_queue(log_queue)  # type: ignore[arg-type]

        _assert_redaction_runs_last()
        record = self._queued_child_record(test_domain, log_queue)
        assert record.causation_id == "[REDACTED]"  # type: ignore[attr-defined]
        assert record.correlation_id == "[REDACTED]"  # type: ignore[attr-defined]

    def test_same_keys_twice_leave_one_redaction_filter(self, telemetry_domain):
        telemetry_domain.config["logging"] = {"redact": ["correlation_id"]}
        telemetry_domain.configure_logging(level="DEBUG", format="json")
        telemetry_domain.configure_logging(level="DEBUG", format="json")
        log_queue: queue.Queue[logging.LogRecord] = queue.Queue()

        _install_worker_log_queue(log_queue)  # type: ignore[arg-type]

        queue_handler = logging.getLogger().handlers[0]
        assert _count(queue_handler, ProteanRedactionFilter) == 1
        assert isinstance(queue_handler.filters[-1], ProteanRedactionFilter)
        _assert_redaction_runs_last()

    def test_handler_filter_with_covered_keys_is_not_added(self, test_domain):
        test_domain.config["logging"] = {"redact": ["correlation_id", "causation_id"]}
        test_domain.configure_logging(level="DEBUG", format="json")
        root = logging.getLogger()
        root.handlers[0].addFilter(ProteanRedactionFilter(["causation_id"]))
        log_queue: queue.Queue[logging.LogRecord] = queue.Queue()

        _install_worker_log_queue(log_queue)  # type: ignore[arg-type]

        queue_handler = root.handlers[0]
        assert _count(queue_handler, ProteanRedactionFilter) == 1
        redaction = [
            f for f in queue_handler.filters if isinstance(f, ProteanRedactionFilter)
        ]
        assert redaction[0] in root.filters


_PROTEAN_FILTERS = (
    ProteanCorrelationFilter,
    OTelTraceContextFilter,
    ProteanRedactionFilter,
)


def _assert_redaction_runs_last() -> None:
    root = logging.getLogger()
    assert root.handlers
    for target in [root, *root.handlers]:
        protean_filters = [f for f in target.filters if isinstance(f, _PROTEAN_FILTERS)]
        assert protean_filters
        assert isinstance(protean_filters[-1], ProteanRedactionFilter)


@pytest.mark.no_test_domain
class TestMoveRedactionFilterLast:
    def test_no_redaction_filter_leaves_filters_alone(self):
        root = logging.getLogger()
        correlation, otel = ProteanCorrelationFilter(), OTelTraceContextFilter()
        root.filters = [correlation, otel]
        handler = _Recorder([])
        handler.filters = [otel, correlation]
        root.handlers = [handler]

        _move_redaction_filter_last()

        assert root.filters == [correlation, otel]
        assert handler.filters == [otel, correlation]

    def test_moves_redaction_after_others_and_keeps_relative_order(self):
        root = logging.getLogger()
        first_redact = ProteanRedactionFilter(["a"])
        second_redact = ProteanRedactionFilter(["b"])
        correlation, otel = ProteanCorrelationFilter(), OTelTraceContextFilter()
        user = logging.Filter("user")
        root.filters = [first_redact, correlation, second_redact, user, otel]
        handler = _Recorder([])
        handler.filters = [second_redact, otel, first_redact, correlation]
        root.handlers = [handler]

        _move_redaction_filter_last()

        assert root.filters == [correlation, user, otel, first_redact, second_redact]
        assert handler.filters == [otel, correlation, second_redact, first_redact]

    def test_filter_after_last_context_filter_stays_after_redaction(self):
        root = logging.getLogger()
        redact, correlation = ProteanRedactionFilter(), ProteanCorrelationFilter()
        user = logging.Filter("user")
        root.filters = [redact, correlation, user]
        root.handlers = []

        _move_redaction_filter_last()

        assert root.filters == [correlation, redact, user]

    def test_redaction_already_after_context_filters_is_left_alone(self):
        root = logging.getLogger()
        redact, correlation = ProteanRedactionFilter(), ProteanCorrelationFilter()
        user = logging.Filter("user")
        original = [correlation, redact, user]
        root.filters = original
        root.handlers = []

        _move_redaction_filter_last()

        assert root.filters is original
        assert root.filters == [correlation, redact, user]

    def test_reorder_binds_a_new_list(self):
        root = logging.getLogger()
        redact, correlation = ProteanRedactionFilter(), ProteanCorrelationFilter()
        original = [redact, correlation]
        root.filters = original
        root.handlers = []

        _move_redaction_filter_last()

        assert root.filters == [correlation, redact]
        assert original == [redact, correlation]

    def test_without_handlers_only_root_is_reordered(self):
        root = logging.getLogger()
        redact, correlation = ProteanRedactionFilter(), ProteanCorrelationFilter()
        root.filters = [redact, correlation]
        root.handlers = []

        _move_redaction_filter_last()

        assert root.filters == [correlation, redact]


class TestRedactionRunsAfterContextFilters:
    """Ids written by the context filters are masked when listed in ``redact``."""

    def _format_with_ids(self, records: list[logging.LogRecord]) -> str:
        assert records
        return logging.Formatter(
            "corr=%(correlation_id)s caus=%(causation_id)s %(message)s"
        ).format(records[-1])

    def test_correlation_ids_masked_on_default_path(self, test_domain):
        test_domain.config["logging"] = {"redact": ["correlation_id", "causation_id"]}
        records: list[logging.LogRecord] = []
        with test_domain.domain_context():
            test_domain.configure_logging(level="DEBUG", format="json")
            _record_root_handler(records)
            g.correlation_id = "secret-corr-123"
            g.causation_id = "secret-caus-456"
            logging.getLogger(CHILD_LOGGER).warning("order placed")

        output = self._format_with_ids(records)
        assert output == "corr=[REDACTED] caus=[REDACTED] order placed"
        assert "secret-corr-123" not in output
        assert "secret-caus-456" not in output

    def test_ids_masked_on_dict_config_path_with_telemetry(self, telemetry_domain):
        telemetry_domain.config["logging"] = {
            "redact": ["correlation_id", "causation_id", "trace_id", "span_id"]
        }
        records: list[logging.LogRecord] = []
        with telemetry_domain.domain_context():
            telemetry_domain.configure_logging(dict_config=_dict_config(records))
            g.correlation_id = "secret-corr-123"
            g.causation_id = "secret-caus-456"
            tracer = SDKTracerProvider().get_tracer("test")
            with tracer.start_as_current_span("redacted-span"):
                logging.getLogger(CHILD_LOGGER).warning("order placed")

        assert self._format_with_ids(records) == (
            "corr=[REDACTED] caus=[REDACTED] order placed"
        )
        assert records[-1].trace_id == "[REDACTED]"  # type: ignore[attr-defined]
        assert records[-1].span_id == "[REDACTED]"  # type: ignore[attr-defined]

    def test_correlation_ids_masked_on_root_logger_records(self, test_domain):
        test_domain.config["logging"] = {"redact": ["correlation_id"]}
        records: list[logging.LogRecord] = []
        with test_domain.domain_context():
            test_domain.configure_logging(level="DEBUG", format="json")
            _record_root_handler(records)
            g.correlation_id = "secret-corr-123"
            logging.getLogger().warning("on root")

        assert records
        assert records[-1].correlation_id == "[REDACTED]"  # type: ignore[attr-defined]

    def test_trace_ids_masked_with_telemetry(self, telemetry_domain):
        telemetry_domain.config["logging"] = {"redact": ["trace_id", "span_id"]}
        telemetry_domain.configure_logging(level="DEBUG", format="json")
        records: list[logging.LogRecord] = []
        _record_root_handler(records)
        tracer = SDKTracerProvider().get_tracer("test")
        with tracer.start_as_current_span("redacted-span") as span:
            _log_on_child()
        context = span.get_span_context()

        assert records
        assert records[-1].trace_id == "[REDACTED]"  # type: ignore[attr-defined]
        assert records[-1].span_id == "[REDACTED]"  # type: ignore[attr-defined]
        assert f"{context.trace_id:032x}" not in vars(records[-1]).values()

    def test_ids_kept_when_not_listed_in_redact(self, telemetry_domain):
        telemetry_domain.config["logging"] = {"redact": ["password"]}
        records: list[logging.LogRecord] = []
        with telemetry_domain.domain_context():
            telemetry_domain.configure_logging(level="DEBUG", format="json")
            _record_root_handler(records)
            g.correlation_id = "corr-123"
            tracer = SDKTracerProvider().get_tracer("test")
            with tracer.start_as_current_span("plain-span") as span:
                _log_on_child(password="s3cret")
        context = span.get_span_context()

        assert records
        assert records[-1].correlation_id == "corr-123"  # type: ignore[attr-defined]
        assert records[-1].trace_id == f"{context.trace_id:032x}"  # type: ignore[attr-defined]
        assert records[-1].password == "[REDACTED]"  # type: ignore[attr-defined]

    @pytest.mark.parametrize("telemetry", [False, True])
    def test_order_on_default_path_after_one_and_two_calls(
        self, test_domain, telemetry
    ):
        test_domain.config["telemetry"] = {"enabled": telemetry}
        test_domain.config["logging"] = {"redact": ["correlation_id"]}

        test_domain.configure_logging(level="DEBUG", format="json")
        _assert_redaction_runs_last()

        test_domain.configure_logging(level="DEBUG", format="json")
        _assert_redaction_runs_last()

    def test_order_on_dict_config_path_after_one_and_two_calls(self, test_domain):
        test_domain.config["telemetry"] = {"enabled": True}
        records: list[logging.LogRecord] = []
        config = _dict_config(records)

        test_domain.configure_logging(dict_config=config, redact=["correlation_id"])
        _assert_redaction_runs_last()

        test_domain.configure_logging(dict_config=config, redact=["correlation_id"])
        _assert_redaction_runs_last()

        with test_domain.domain_context():
            g.correlation_id = "secret-corr-123"
            _log_on_child()
        assert records
        assert records[-1].correlation_id == "[REDACTED]"  # type: ignore[attr-defined]

    @pytest.mark.no_test_domain
    def test_dict_config_call_reorders_redaction_already_on_root(self):
        records: list[logging.LogRecord] = []
        config = _dict_config(records)
        root = logging.getLogger()
        # User code (or an older Protean) can leave redaction before the
        # correlation filter on the root logger.
        earlier_redact = ProteanRedactionFilter(["correlation_id"])
        root.filters = [earlier_redact, ProteanCorrelationFilter()]
        with patch.dict("os.environ", {}, clear=True):
            configure_logging(dict_config=config, redact=["correlation_id"])

        _assert_redaction_runs_last()
        assert root.filters[-1] is earlier_redact

    @pytest.mark.no_test_domain
    def test_default_path_call_reorders_redaction_already_on_root(self):
        root = logging.getLogger()
        earlier_redact = ProteanRedactionFilter(["correlation_id"])
        root.filters = [earlier_redact, ProteanCorrelationFilter()]
        with patch.dict("os.environ", {}, clear=True):
            configure_logging(level="DEBUG", format="json", redact=["correlation_id"])

        assert isinstance(root.filters[-1], ProteanRedactionFilter)
        assert isinstance(root.filters[0], ProteanCorrelationFilter)

    def test_user_filter_added_between_calls_keeps_its_place(self, test_domain):
        test_domain.config["logging"] = {"redact": ["password"]}
        test_domain.configure_logging(level="DEBUG", format="json")
        root = logging.getLogger()
        audit = logging.Filter("audit")
        root.addFilter(audit)

        test_domain.configure_logging(level="DEBUG", format="json")

        assert root.filters[-1] is audit
        assert isinstance(root.filters[-2], ProteanRedactionFilter)

    def test_redaction_declared_on_root_in_dict_config_covers_handlers(
        self, test_domain
    ):
        records: list[logging.LogRecord] = []
        config = _dict_config(records)
        config["filters"] = {
            "red": {"()": lambda: ProteanRedactionFilter(["correlation_id"])}
        }
        config["root"]["filters"] = ["red"]
        test_domain.config["logging"] = {}

        test_domain.configure_logging(dict_config=config)

        handler = logging.getLogger().handlers[0]
        assert _count(handler, ProteanRedactionFilter) == 1
        _assert_redaction_runs_last()
        with test_domain.domain_context():
            g.correlation_id = "secret-corr-123"
            _log_on_child()
        assert records
        assert records[-1].correlation_id == "[REDACTED]"  # type: ignore[attr-defined]

    def test_dict_config_reconfigure_with_new_key_masks_both_keys(self, test_domain):
        test_domain.config["telemetry"] = {"enabled": False}
        test_domain.config["logging"] = {}
        records: list[logging.LogRecord] = []
        config = _dict_config(records)

        test_domain.configure_logging(dict_config=config, redact=["correlation_id"])
        test_domain.configure_logging(dict_config=config, redact=["causation_id"])

        handler = logging.getLogger().handlers[0]
        assert _count(handler, ProteanRedactionFilter) == 2
        _assert_redaction_runs_last()
        with test_domain.domain_context():
            g.correlation_id = "secret-corr-123"
            g.causation_id = "secret-caus-456"
            _log_on_child()
        assert records
        assert records[-1].correlation_id == "[REDACTED]"  # type: ignore[attr-defined]
        assert records[-1].causation_id == "[REDACTED]"  # type: ignore[attr-defined]

    def test_worker_queue_handler_keeps_redaction_last(self, test_domain):
        test_domain.config["logging"] = {"redact": ["correlation_id"]}
        test_domain.configure_logging(level="DEBUG", format="json")
        log_queue: queue.Queue[logging.LogRecord] = queue.Queue()

        _install_worker_log_queue(log_queue)  # type: ignore[arg-type]

        _assert_redaction_runs_last()
