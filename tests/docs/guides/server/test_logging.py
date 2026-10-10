"""The examples on the logging guide behave as the page says.

``tests/conftest.py`` saves the process-wide logging and structlog state
before each test and restores it afterwards, so these tests may change it.
"""

import json
import logging

import pytest
import structlog

from protean.integrations.logging import (
    ProteanCorrelationFilter,
    protean_correlation_processor,
)
from protean.utils.globals import g
from protean.utils.logging import configure_logging
from tests.docs.support import load_example

pytestmark = pytest.mark.no_test_domain

ENV_VARS = (
    "PROTEAN_ENV",
    "ENV",
    "ENVIRONMENT",
    "PROTEAN_LOG_LEVEL",
    "PROTEAN_NO_AUTO_LOGGING",
)


@pytest.fixture
def no_env_hints(monkeypatch):
    for name in ENV_VARS:
        monkeypatch.delenv(name, raising=False)


def _bare_root():
    """Strip the root logger of handlers, filters and level.

    ``Domain.init()`` skips auto-configuration when the root logger already
    has a handler. pytest attaches its capture handlers again just before the
    test body runs, so the test body calls this, not a fixture.
    """
    root = logging.getLogger()
    root.handlers = []
    root.filters = []
    root.setLevel(logging.WARNING)
    return root


def _json_lines(text):
    return [json.loads(line) for line in text.splitlines() if line.startswith("{")]


def _has_correlation_filter(filterer):
    return any(isinstance(f, ProteanCorrelationFilter) for f in filterer.filters)


def test_domain_init_configures_logging_at_info_with_correlation(no_env_hints):
    bare_root = _bare_root()
    load_example("guides/server/logging/quick-start/001.py")

    assert bare_root.handlers
    assert bare_root.level == logging.INFO
    assert logging.getLogger("protean.core").level == logging.WARNING
    assert logging.getLogger("protean.adapters").level == logging.WARNING
    assert _has_correlation_filter(bare_root)
    for handler in bare_root.handlers:
        assert _has_correlation_filter(handler)
    assert protean_correlation_processor in structlog.get_config()["processors"]


def test_domain_init_logs_at_debug_in_development(no_env_hints, monkeypatch):
    bare_root = _bare_root()
    monkeypatch.setenv("PROTEAN_ENV", "development")
    load_example("guides/server/logging/quick-start/001.py")

    assert bare_root.level == logging.DEBUG


def test_domain_init_leaves_logging_alone_when_auto_logging_is_off(
    no_env_hints, monkeypatch
):
    bare_root = _bare_root()
    monkeypatch.setenv("PROTEAN_NO_AUTO_LOGGING", "1")
    load_example("guides/server/logging/quick-start/001.py")

    assert bare_root.handlers == []
    assert bare_root.level == logging.WARNING


def test_get_logger_passes_keyword_arguments_as_event_fields():
    with structlog.testing.capture_logs() as logs:
        load_example("guides/server/logging/001.py")

    events = {e["event"]: e for e in logs}
    assert events["order_placed"]["order_id"] == "ord-123"
    assert events["order_placed"]["total"] == 99.95
    assert events["payment_refunded"]["amount"] == 19.99
    assert events["payment_refunded"]["reason"] == "customer_request"


@pytest.mark.xfail(
    strict=True,
    reason=(
        "_setup_structlog renders a get_logger() event to JSON, and the stdlib "
        "handler's ProcessorFormatter renders it again, so the keyword "
        "arguments end up inside the outer event string"
    ),
)
def test_get_logger_writes_keyword_arguments_as_top_level_json_fields(
    no_env_hints, capsys
):
    _bare_root()
    configure_logging(level="INFO", format="json")

    load_example("guides/server/logging/001.py")

    events = {e["event"]: e for e in _json_lines(capsys.readouterr().err)}
    assert events["order_placed"]["order_id"] == "ord-123"
    assert events["order_placed"]["total"] == 99.95


def test_add_context_tags_records_until_clear_context():
    with structlog.testing.capture_logs(
        processors=[structlog.contextvars.merge_contextvars]
    ) as logs:
        example = load_example("guides/server/logging/001.py")
        example.logger.info("after_scope")

    events = {e["event"]: e for e in logs}
    for name in ("processing", "processed"):
        assert events[name]["request_id"] == "abc-123"
        assert events[name]["tenant_id"] == "tenant-42"
    assert "request_id" not in events["order_placed"]
    assert "request_id" not in events["after_scope"]


def test_configure_logging_sets_debug_level_and_json_output(no_env_hints, capsys):
    bare_root = _bare_root()
    load_example("guides/server/logging/002.py")

    assert bare_root.level == logging.DEBUG
    assert bare_root.handlers
    for handler in bare_root.handlers:
        assert _has_correlation_filter(handler)

    logging.getLogger("myapp.orders").debug("order checked")

    events = {e["event"]: e for e in _json_lines(capsys.readouterr().err)}
    assert events["order checked"]["level"] == "debug"
    assert events["order checked"]["logger"] == "myapp.orders"
    assert events["order checked"]["correlation_id"] == ""


def test_configure_logging_again_replaces_the_handlers(no_env_hints):
    bare_root = _bare_root()
    example = load_example("guides/server/logging/002.py")
    first_handlers = list(bare_root.handlers)
    assert first_handlers

    example.domain.configure_logging(level="WARNING")

    assert bare_root.level == logging.WARNING
    assert bare_root.handlers
    assert not set(bare_root.handlers) & set(first_handlers)
    for handler in bare_root.handlers:
        assert _has_correlation_filter(handler)


def _access_record(caplog, example, **command_fields):
    example.domain.init(traverse=False)
    with (
        caplog.at_level(logging.INFO, logger="protean.access"),
        example.domain.domain_context(),
    ):
        example.domain.process(
            example.PlaceOrder(customer_id="cust-1", total=120.5, **command_fields),
            asynchronous=False,
        )

    records = [r for r in caplog.records if r.name == "protean.access"]
    assert len(records) == 1
    return records[0]


def test_bind_event_context_adds_business_fields_to_the_wide_event(caplog):
    example = load_example("guides/server/logging/003.py")

    record = _access_record(caplog, example, user_tier="gold")

    assert record.getMessage() == "access.handler_completed"
    assert record.status == "ok"
    assert record.message_type == "Orders.PlaceOrder.v1"
    assert record.user_tier == "gold"
    assert record.order_total == 120.5
    assert record.coupon_applied is False


def test_bind_event_context_reports_an_applied_coupon(caplog):
    example = load_example("guides/server/logging/003.py")

    record = _access_record(caplog, example, coupon_code="SPRING10")

    assert record.user_tier == "standard"
    assert record.coupon_applied is True


class _User:
    def __init__(self, id, allowed):
        self.id = id
        self.allowed = allowed

    def can_access(self, resource):
        return self.allowed


class _Resource:
    id = "res-7"


def test_denied_access_logs_a_security_event_and_raises(caplog):
    example = load_example("guides/server/logging/004.py")
    example.domain.init(traverse=False)

    with (
        caplog.at_level(logging.WARNING, logger="protean.security"),
        example.domain.domain_context(),
    ):
        g.correlation_id = "req-55"
        with pytest.raises(example.PermissionDenied):
            example.check_admin_access(_User("user-1", allowed=False), _Resource())

    records = [r for r in caplog.records if r.name == "protean.security"]
    assert len(records) == 1
    record = records[0]
    assert record.levelno == logging.WARNING
    assert record.getMessage() == "validation_failed"
    assert record.aggregate == "Resource"
    assert record.aggregate_id == "res-7"
    assert record.user_id == "user-1"
    assert record.reason == "not_authorized"
    assert record.correlation_id == "req-55"


def test_allowed_access_logs_no_security_event(caplog):
    example = load_example("guides/server/logging/004.py")

    with caplog.at_level(logging.WARNING, logger="protean.security"):
        example.check_admin_access(_User("user-1", allowed=True), _Resource())

    assert [r for r in caplog.records if r.name == "protean.security"] == []


def test_manual_wiring_puts_the_filter_on_each_root_handler(no_env_hints):
    bare_root = _bare_root()
    handlers = [logging.StreamHandler(), logging.StreamHandler()]
    bare_root.handlers = list(handlers)

    load_example("guides/server/logging/005.py")

    for handler in handlers:
        assert _has_correlation_filter(handler)
    assert not _has_correlation_filter(bare_root)


def test_configure_for_testing_sets_warning_and_drops_file_handlers(
    no_env_hints, tmp_path
):
    bare_root = _bare_root()
    file_handler = logging.FileHandler(tmp_path / "app.log")
    stream_handler = logging.StreamHandler()
    bare_root.handlers = [file_handler, stream_handler]
    bare_root.setLevel(logging.DEBUG)

    load_example("guides/server/logging/006.py")
    file_handler.close()

    assert bare_root.level == logging.WARNING
    assert bare_root.handlers == [stream_handler]
