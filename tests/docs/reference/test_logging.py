"""The examples on ``docs/reference/logging.md`` behave as the page says.

``tests/conftest.py`` saves the process-wide logging and structlog state
before each test and restores it afterwards, so these tests may change it.
"""

import json
import logging
import logging.handlers
import shutil
import sys
from unittest.mock import patch

import pytest
import structlog
from fastapi import FastAPI
from fastapi.testclient import TestClient

from protean import Domain, handle
from protean.fields import String
from protean.integrations.fastapi import DomainContextMiddleware
from protean.integrations.logging import (
    DEFAULT_REDACT_KEYS,
    ProteanCorrelationFilter,
    protean_correlation_processor,
)
from protean.utils.globals import g
from protean.utils.logging import TailSamplingFilter
from tests.docs.support import DOCS_SRC, load_example
from tests.support.snippets import read_include

pytestmark = pytest.mark.no_test_domain

CONFIG_DIR = DOCS_SRC / "reference/logging"

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

    pytest attaches its capture handlers again just before the test body
    runs, so the test body calls this, not a fixture.
    """
    root = logging.getLogger()
    root.handlers = []
    root.filters = []
    root.setLevel(logging.WARNING)
    return root


def _json_lines(text):
    return [json.loads(line) for line in text.splitlines() if line.startswith("{")]


def _domain_from(tmp_path, toml_name, name="Logging"):
    shutil.copy(CONFIG_DIR / toml_name, tmp_path / "domain.toml")
    return Domain(root_path=str(tmp_path), name=name)


def _correlation_filters(filterer):
    return [f for f in filterer.filters if isinstance(f, ProteanCorrelationFilter)]


def _renders_json(handler):
    return isinstance(
        handler.formatter.processors[-1], structlog.processors.JSONRenderer
    )


class _Capture(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)


# --- [logging] config section ---


def test_logging_toml_reaches_the_domain_config(tmp_path):
    domain = _domain_from(tmp_path, "logging.toml")

    config = domain.config["logging"]
    assert config["level"] == "INFO"
    assert config["format"] == "auto"
    assert config["log_dir"] == ""
    assert config["log_file_prefix"] == "protean"
    assert config["max_bytes"] == 10485760
    assert config["backup_count"] == 5
    assert config["slow_handler_threshold_ms"] == 500
    assert config["slow_query_threshold_ms"] == 100
    assert config["slow_query_truncate_chars"] == 500
    assert config["redact"] == list(DEFAULT_REDACT_KEYS)
    assert config["per_logger"] == {"protean.server.engine": "WARNING"}


def test_logging_toml_drives_configure_logging(tmp_path, no_env_hints, capsys):
    domain = _domain_from(tmp_path, "logging.toml")
    root = _bare_root()

    domain.configure_logging()

    assert root.level == logging.INFO
    assert logging.getLogger("protean.server.engine").level == logging.WARNING
    # An empty log_dir leaves only the console handler, and it writes to stderr
    [console] = root.handlers
    assert type(console) is logging.StreamHandler
    assert console.stream is sys.stderr
    # format = "auto" with no environment set picks the console renderer
    assert not _renders_json(console)

    logging.getLogger("myapp.orders").info("order checked")
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "order checked" in captured.err


def test_auto_format_picks_json_in_production_and_redacts_the_listed_keys(
    tmp_path, no_env_hints, monkeypatch, capsys
):
    monkeypatch.setenv("PROTEAN_ENV", "production")
    domain = _domain_from(tmp_path, "logging.toml")
    _bare_root()

    domain.configure_logging()
    logging.getLogger("myapp.orders").info(
        "order checked", extra={"order_id": "ord-1", "API_KEY": "k-123"}
    )

    [record] = _json_lines(capsys.readouterr().err)
    assert record["event"] == "order checked"
    assert record["level"] == "info"
    assert record["logger"] == "myapp.orders"
    assert record["order_id"] == "ord-1"
    assert record["API_KEY"] == "[REDACTED]"
    assert record["correlation_id"] == ""
    assert record["causation_id"] == ""


def test_protean_log_level_overrides_the_toml_level(
    tmp_path, no_env_hints, monkeypatch
):
    monkeypatch.setenv("PROTEAN_LOG_LEVEL", "ERROR")
    domain = _domain_from(tmp_path, "logging.toml")
    root = _bare_root()

    domain.configure_logging()

    assert root.level == logging.ERROR


def test_explicit_keyword_arguments_override_the_env_var_and_the_toml(
    tmp_path, no_env_hints, monkeypatch
):
    monkeypatch.setenv("PROTEAN_LOG_LEVEL", "ERROR")
    domain = _domain_from(tmp_path, "logging.toml")
    root = _bare_root()
    log_dir = tmp_path / "logs"

    domain.configure_logging(level="DEBUG", log_dir=str(log_dir))
    logging.getLogger("myapp").error("boom")
    for handler in root.handlers:
        handler.flush()

    assert root.level == logging.DEBUG
    files = [h for h in root.handlers if isinstance(h, logging.FileHandler)]
    assert all(isinstance(h, logging.handlers.RotatingFileHandler) for h in files)
    assert sorted(p.name for p in log_dir.iterdir()) == [
        "protean.log",
        "protean_error.log",
    ]
    assert "boom" in (log_dir / "protean_error.log").read_text()
    for handler in files:
        handler.close()


# --- [logging.sampling] ---


def test_sampling_toml_reaches_the_domain_config(tmp_path):
    domain = _domain_from(tmp_path, "sampling.toml")

    assert domain.config["logging"]["sampling"] == {
        "enabled": True,
        "default_rate": 0.05,
        "always_keep_errors": True,
        "always_keep_slow": True,
        "critical_streams": ["*.Payment*", "*.Auth*"],
    }


@pytest.fixture
def sampled_access(tmp_path, no_env_hints):
    """A domain configured from sampling.toml, and a handler on protean.access."""
    domain = _domain_from(tmp_path, "sampling.toml", name="Billing")

    @domain.aggregate
    class Card:
        number: String()

    @domain.command(part_of=Card)
    class AuthorizeCard:
        number: String()

    @domain.command_handler(part_of=Card)
    class CardHandler:
        @handle(AuthorizeCard)
        def authorize(self, command):
            pass

    domain.init(traverse=False)
    _bare_root()
    domain.configure_logging()

    access = logging.getLogger("protean.access")
    capture = _Capture()
    access.addHandler(capture)
    yield domain, AuthorizeCard, access, capture.records
    access.removeHandler(capture)


def test_sampling_installs_a_filter_on_the_access_logger(sampled_access):
    _, _, access, _ = sampled_access

    [sampling] = [f for f in access.filters if isinstance(f, TailSamplingFilter)]
    assert sampling.default_rate == 0.05
    assert sampling.critical_streams == ("*.Payment*", "*.Auth*")


def test_a_critical_stream_wide_event_is_always_kept(sampled_access):
    domain, AuthorizeCard, _, records = sampled_access

    with domain.domain_context():
        domain.process(AuthorizeCard(number="4111"), asynchronous=False)

    [record] = records
    assert record.getMessage() == "access.handler_completed"
    assert record.message_type == "Billing.AuthorizeCard.v1"
    assert record.sampling_decision == "kept"
    assert record.sampling_rule == "critical_stream"
    assert record.sampling_rate == 1.0


def test_errors_are_kept_and_happy_path_events_are_sampled(sampled_access):
    _, _, access, records = sampled_access

    access.error("access.handler_failed", extra={"status": "failed"})
    [error] = records
    assert error.sampling_rule == "error"
    assert error.sampling_rate == 1.0

    records.clear()
    # Evenly spaced draws make the 5% rate keep exactly 10 of 200
    draws = [i / 200 for i in range(200)]
    with patch("protean.utils.logging.random.random", side_effect=draws):
        for _ in range(200):
            access.info(
                "access.handler_completed",
                extra={"status": "ok", "message_type": "Billing.UpdateAddress.v1"},
            )
    assert len(records) == 10
    assert {r.sampling_rule for r in records} == {"random"}
    assert {r.sampling_rate for r in records} == {0.05}


def test_sampling_leaves_other_loggers_alone(sampled_access):
    capture = _Capture()
    other = logging.getLogger("myapp.orders")
    other.addHandler(capture)
    try:
        for _ in range(20):
            other.info("order checked")
    finally:
        other.removeHandler(capture)

    assert len(capture.records) == 20
    assert not hasattr(capture.records[0], "sampling_decision")


# --- [logging.http] ---


def test_http_toml_reaches_the_domain_config(tmp_path):
    domain = _domain_from(tmp_path, "http.toml")

    assert domain.config["logging"]["http"] == {
        "enabled": True,
        "exclude_paths": ["/healthz", "/readyz", "/metrics"],
        "log_request_headers": False,
        "log_response_headers": False,
    }


@pytest.mark.fastapi
def test_excluded_paths_emit_no_http_wide_event(tmp_path, caplog):
    caplog.set_level(logging.INFO, logger="protean.access.http")
    domain = _domain_from(tmp_path, "http.toml", name="Shop")
    domain.init(traverse=False)
    app = FastAPI()
    app.add_middleware(DomainContextMiddleware, route_domain_map={"/": domain})

    @app.get("/healthz")
    def healthz() -> dict:
        return {"ok": True}

    @app.get("/orders")
    def orders() -> list:
        return []

    client = TestClient(app)
    client.get("/healthz")
    client.get("/orders")

    events = [r for r in caplog.records if r.name == "protean.access.http"]
    assert [e.http_path for e in events] == ["/orders"]
    assert not hasattr(events[0], "http_request_headers")
    assert not hasattr(events[0], "http_response_headers")


# --- Public API ---


@pytest.mark.parametrize(
    ("env", "level", "json_output"),
    [
        ("development", logging.DEBUG, False),
        ("production", logging.INFO, True),
        ("staging", logging.INFO, True),
        ("test", logging.WARNING, False),
        ("qa", logging.INFO, False),
        (None, logging.INFO, False),
    ],
)
def test_configure_logging_defaults_follow_the_environment(
    no_env_hints, monkeypatch, env, level, json_output
):
    if env is not None:
        monkeypatch.setenv("PROTEAN_ENV", env)
    root = _bare_root()

    load_example("reference/logging/001.py")

    assert root.level == level
    [console] = root.handlers
    assert _renders_json(console) is json_output


def test_configure_logging_without_redact_masks_nothing(
    no_env_hints, monkeypatch, capsys
):
    monkeypatch.setenv("PROTEAN_ENV", "production")
    _bare_root()

    load_example("reference/logging/001.py")
    logging.getLogger("myapp").info("login", extra={"password": "hunter2"})

    [record] = _json_lines(capsys.readouterr().err)
    assert record["password"] == "hunter2"


def test_domain_configure_logging_applies_explicit_values(no_env_hints, capsys):
    root = _bare_root()

    example = load_example("reference/logging/002.py")

    # Run the two calls again one at a time: the first applies the domain's
    # [logging] level, the second's explicit values win over it
    first, second = read_include(
        "reference/logging/002.py:domain-configure-logging", [DOCS_SRC]
    ).splitlines()
    _bare_root()
    exec(first, vars(example))
    assert root.level == logging.INFO
    exec(second, vars(example))

    assert root.level == logging.DEBUG
    assert protean_correlation_processor in structlog.get_config()["processors"]
    # Calling it twice leaves one handler and one correlation filter on each
    [console] = root.handlers
    assert len(_correlation_filters(root)) == 1
    assert len(_correlation_filters(console)) == 1

    logging.getLogger("myapp.orders").debug(
        "order checked", extra={"password": "hunter2"}
    )
    [record] = _json_lines(capsys.readouterr().err)
    assert record["level"] == "debug"
    assert record["correlation_id"] == ""
    # The domain's default [logging].redact masks the built-in keys
    assert record["password"] == "[REDACTED]"


def test_get_logger_passes_keyword_arguments_as_event_fields():
    with structlog.testing.capture_logs() as logs:
        load_example("reference/logging/003.py")

    events = {e["event"]: e for e in logs}
    assert events["order_placed"]["order_id"] == "ord-123"
    assert events["order_placed"]["total"] == 99.95


def test_add_context_tags_records_until_clear_context():
    with structlog.testing.capture_logs(
        processors=[structlog.contextvars.merge_contextvars]
    ) as logs:
        load_example("reference/logging/003.py")

    events = {e["event"]: e for e in logs}
    assert events["checkout_started"]["request_id"] == "req-abc"
    assert events["checkout_started"]["tenant_id"] == "tenant-42"
    assert "request_id" not in structlog.contextvars.get_contextvars()


def test_unbind_event_context_removes_only_the_named_field():
    example = load_example("reference/logging/003.py")

    with structlog.testing.capture_logs(
        processors=[structlog.contextvars.merge_contextvars]
    ) as logs:
        example.logger.info("next_record")

    [event] = logs
    assert event["user_id"] == "u-42"
    assert "plan" not in event


def test_log_method_call_logs_start_and_end_at_debug(no_env_hints):
    example = load_example("reference/logging/004.py")

    with structlog.testing.capture_logs() as logs:
        example.PlaceOrderHandler().handle("place-order")

    assert [(e["event"], e["log_level"]) for e in logs] == [
        ("method_call_start", "debug"),
        ("method_call_end", "debug"),
    ]
    assert logs[0]["method"] == "handle"
    assert logs[0]["args"] == ("place-order",)
    assert logs[1]["result"] is None


def test_log_method_call_arguments_pass_through_redaction(no_env_hints, capsys):
    example = load_example("reference/logging/004.py")
    _bare_root()
    load_example("reference/logging/002.py")

    example.PlaceOrderHandler().handle({"order_id": "ord-1", "token": "t-secret"})

    err = capsys.readouterr().err
    assert "method_call_start" in err
    assert "ord-1" in err
    assert "t-secret" not in err
    assert "[REDACTED]" in err


def test_configure_for_testing_sets_warning_and_drops_file_handlers(
    no_env_hints, tmp_path
):
    root = _bare_root()
    file_handler = logging.FileHandler(tmp_path / "app.log")
    stream_handler = logging.StreamHandler()
    root.handlers = [file_handler, stream_handler]
    root.setLevel(logging.DEBUG)

    load_example("reference/logging/005.py")
    file_handler.close()

    assert root.level == logging.WARNING
    assert root.handlers == [stream_handler]


def test_log_security_event_warns_on_the_security_logger(caplog):
    caplog.set_level(logging.WARNING, logger="protean.security")
    domain = Domain(name="Orders")
    domain.init(traverse=False)

    with domain.domain_context():
        g.correlation_id = "req-55"
        load_example("reference/logging/006.py")

    [record] = [r for r in caplog.records if r.name == "protean.security"]
    assert record.levelno == logging.WARNING
    assert record.getMessage() == "invariant_failed"
    assert record.aggregate == "Order"
    assert record.aggregate_id == "ord-9b1c"
    assert record.invariant == "total_must_equal_sum_of_items"
    assert record.correlation_id == "req-55"
    assert record.causation_id == ""


def test_security_event_constants_hold_the_documented_names():
    example = load_example("reference/logging/006.py")

    assert example.event_types == (
        "invariant_failed",
        "validation_failed",
        "invalid_operation",
        "invalid_state",
    )


def test_log_snapshot_event_warns_on_the_snapshot_logger(caplog):
    caplog.set_level(logging.WARNING, logger="protean.snapshot")

    load_example("reference/logging/007.py")

    [record] = [r for r in caplog.records if r.name == "protean.snapshot"]
    assert record.levelno == logging.WARNING
    assert record.getMessage() == "snapshot_discarded"
    assert record.aggregate == "User"
    assert record.aggregate_id == "user-1"
    assert record.reason == "extra fields not permitted"
    assert record.correlation_id == ""
    assert record.causation_id == ""


# --- Redaction ---


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Domain.configure_logging skips redaction when [logging].redact is an "
        "empty list, so the default keys are not applied"
    ),
)
def test_an_empty_redact_list_keeps_the_default_keys(
    tmp_path, no_env_hints, monkeypatch, capsys
):
    monkeypatch.setenv("PROTEAN_ENV", "production")
    (tmp_path / "domain.toml").write_text("[logging]\nredact = []\n")
    domain = Domain(root_path=str(tmp_path), name="Logging")
    _bare_root()

    domain.configure_logging()
    logging.getLogger("myapp").info("login", extra={"password": "hunter2"})

    [record] = _json_lines(capsys.readouterr().err)
    assert record["password"] == "[REDACTED]"


def test_redact_toml_extends_the_default_keys(
    tmp_path, no_env_hints, monkeypatch, capsys
):
    monkeypatch.setenv("PROTEAN_ENV", "production")
    domain = _domain_from(tmp_path, "redact.toml")
    assert domain.config["logging"]["redact"] == ["x-internal-token", "customer_ssn"]
    _bare_root()

    domain.configure_logging()
    logging.getLogger("myapp").info(
        "customer checked",
        extra={
            "customer_ssn": "123-45-6789",
            "password": "hunter2",
            "headers": {"X-Internal-Token": "abc", "Accept": "text/html"},
        },
    )

    [record] = _json_lines(capsys.readouterr().err)
    assert record["customer_ssn"] == "[REDACTED]"
    assert record["password"] == "[REDACTED]"
    assert record["headers"] == {
        "X-Internal-Token": "[REDACTED]",
        "Accept": "text/html",
    }
