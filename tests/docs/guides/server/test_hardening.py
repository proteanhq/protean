"""The examples on the hardening guide behave as the page says."""

import logging
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from fastapi.testclient import TestClient

from protean.server import Engine
from protean.server.subscription.config_resolver import ConfigResolver
from protean.server.subscription.profiles import SubscriptionType
from tests.docs.support import load_example

pytestmark = pytest.mark.no_test_domain


@pytest.mark.fastapi
def test_health_router_serves_the_liveness_and_readiness_paths():
    example = load_example("guides/server/hardening/001.py")
    example.domain.init(traverse=False)

    client = TestClient(example.app)

    for path in ("/healthz", "/livez"):
        response = client.get(path)
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    readiness = client.get("/readyz")
    assert readiness.status_code == 200
    assert readiness.json()["status"] == "ok"
    checks = readiness.json()["checks"]
    assert set(checks) == {"providers", "brokers", "caches", "event_store"}
    assert checks["providers"]["default"] == "ok"
    assert checks["event_store"] == "ok"
    assert client.get("/metrics").status_code == 404


def test_dlq_maintenance_uses_the_configured_retention_threshold_and_callback():
    example = load_example("guides/server/hardening/002.py")
    example.domain.init(traverse=False)

    engine = Engine(example.domain, test_mode=True)
    maintenance = engine._dlq_maintenance

    assert maintenance is not None
    assert maintenance.retention_hours == 168
    assert maintenance.alert_threshold == 100
    assert maintenance.alert_callback is example.on_dlq_alert


def test_dlq_maintenance_stays_off_without_the_enabled_switch():
    example = load_example("guides/server/hardening/002.py")
    example.domain.config["server"]["dlq"]["enabled"] = False
    example.domain.init(traverse=False)

    assert Engine(example.domain, test_mode=True)._dlq_maintenance is None


def test_dlq_alert_logs_a_warning_when_no_webhook_is_set(monkeypatch, caplog):
    monkeypatch.delenv("SLACK_DLQ_WEBHOOK", raising=False)
    example = load_example("guides/server/hardening/002.py")

    with caplog.at_level(logging.WARNING, logger=example.__name__):
        example.on_dlq_alert(dlq_stream="orders:dlq", depth=150, threshold=100)

    assert "DLQ alert: orders:dlq depth=150 threshold=100" in caplog.messages


def test_dlq_alert_logs_the_failure_when_the_webhook_post_fails(monkeypatch, caplog):
    # Port 9 on loopback refuses the connection, so httpx raises ConnectError.
    monkeypatch.setenv("SLACK_DLQ_WEBHOOK", "http://127.0.0.1:9/hook")
    example = load_example("guides/server/hardening/002.py")

    with caplog.at_level(logging.ERROR, logger=example.__name__):
        example.on_dlq_alert(dlq_stream="orders:dlq", depth=150, threshold=100)

    assert "Failed to post DLQ alert to Slack" in caplog.messages


def test_production_profile_resolves_to_a_stream_subscription_with_dlq():
    example = load_example("guides/server/hardening/003.py")
    example.domain.init(traverse=False)

    config = ConfigResolver(example.domain).resolve(example.OrderEventHandler)

    assert config.subscription_type == SubscriptionType.STREAM
    assert config.enable_dlq is True
    assert config.messages_per_tick == 100


def test_a_field_override_keeps_the_rest_of_the_profile():
    example = load_example("guides/server/hardening/003.py")
    example.domain.init(traverse=False)

    config = ConfigResolver(example.domain).resolve(example.BulkOrderHandler)

    assert config.messages_per_tick == 50
    assert config.subscription_type == SubscriptionType.STREAM
    assert config.enable_dlq is True
    assert config.blocking_timeout_ms == 5000


@pytest.mark.xfail(
    strict=True,
    reason=(
        "ConfigResolver builds SubscriptionConfig from a field list that leaves "
        "out dlq_retention_hours and dlq_alert_threshold, so the per-handler "
        "DLQ overrides are dropped"
    ),
)
def test_per_handler_dlq_overrides_reach_the_subscription_config():
    example = load_example("guides/server/hardening/003.py")
    example.domain.init(traverse=False)

    config = ConfigResolver(example.domain).resolve(example.AuditHandler)

    assert config.dlq_retention_hours == 720
    assert config.dlq_alert_threshold == 10


def test_closing_the_domain_runs_after_the_work(caplog):
    example = load_example("guides/server/hardening/004.py")
    example.domain.init(traverse=False)

    def work():
        logging.getLogger("tooling").info("work ran")

    example.do_the_work = work
    with caplog.at_level(logging.INFO):
        example.run_tool()

    messages = caplog.messages
    assert messages.index("work ran") < messages.index("Domain infrastructure closed")


def test_closing_the_domain_runs_when_the_work_fails(caplog):
    example = load_example("guides/server/hardening/004.py")
    example.domain.init(traverse=False)

    def failing_work():
        raise RuntimeError("tool failed")

    example.do_the_work = failing_work
    with caplog.at_level(logging.INFO, logger="protean.domain"):
        with pytest.raises(RuntimeError, match="tool failed"):
            example.run_tool()

    assert "Domain infrastructure closed" in caplog.messages


class _RejectingWebhook(BaseHTTPRequestHandler):
    def do_POST(self):
        self.rfile.read(int(self.headers["Content-Length"]))
        self.send_response(500)
        self.end_headers()

    def log_message(self, *args):
        pass


def test_dlq_alert_logs_the_failure_when_the_webhook_rejects_the_post(
    monkeypatch, caplog
):
    server = HTTPServer(("127.0.0.1", 0), _RejectingWebhook)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        monkeypatch.setenv(
            "SLACK_DLQ_WEBHOOK", f"http://127.0.0.1:{server.server_port}/hook"
        )
        example = load_example("guides/server/hardening/002.py")

        with caplog.at_level(logging.ERROR, logger=example.__name__):
            example.on_dlq_alert(dlq_stream="orders:dlq", depth=150, threshold=100)
    finally:
        server.shutdown()
        server.server_close()

    assert "Failed to post DLQ alert to Slack" in caplog.messages
