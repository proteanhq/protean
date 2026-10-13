"""The examples on ``docs/reference/server/hardening.md`` behave as the page says."""

import logging
import shutil

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from protean import Domain
from protean.integrations.fastapi.health import create_health_router
from protean.server import Engine
from protean.server.health import HealthServer
from tests.docs.support import DOCS_SRC, load_example

pytestmark = pytest.mark.no_test_domain

EXAMPLES = DOCS_SRC / "reference/server/hardening"


def domain_from(toml: str, tmp_path) -> Domain:
    shutil.copy(EXAMPLES / toml, tmp_path / "domain.toml")
    return Domain(root_path=str(tmp_path), name="Hardening")


def test_database_pool_keys_reach_the_default_database(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://app@db/orders")

    database = domain_from("database_pool.toml", tmp_path).config["databases"][
        "default"
    ]

    assert database["provider"] == "postgresql"
    assert database["database_uri"] == "postgresql://app@db/orders"
    assert database["pool_size"] == 10
    assert database["max_overflow"] == 20
    assert database["pool_recycle"] == 1800


def test_message_db_max_connections_sits_beside_the_database_uri(tmp_path, monkeypatch):
    monkeypatch.setenv("MESSAGE_DB_URL", "postgresql://message_store@db/message_store")

    event_store = domain_from("message_db.toml", tmp_path).config["event_store"]

    assert event_store["provider"] == "message_db"
    assert event_store["database_uri"] == "postgresql://message_store@db/message_store"
    assert event_store["max_connections"] == 20


def test_port_auto_increment_turns_on_for_the_health_server(tmp_path):
    domain = domain_from("health.toml", tmp_path)
    domain.init(traverse=False)

    assert domain.config["server"]["health"]["port_auto_increment"] is True
    # The keys the file leaves out keep their defaults.
    assert domain.config["server"]["health"]["port"] == 8080

    health = HealthServer(Engine(domain, test_mode=True))
    assert health.port_auto_increment is True


def test_circuit_breaker_keys_load_under_stream_subscription(tmp_path):
    stream = domain_from("circuit_breaker.toml", tmp_path).config["server"][
        "stream_subscription"
    ]

    assert stream["circuit_breaker_threshold"] == 10
    assert stream["circuit_breaker_reset_seconds"] == 60


def test_drain_timeout_sets_the_engine_drain_window(tmp_path):
    domain = domain_from("drain_timeout.toml", tmp_path)
    domain.init(traverse=False)

    assert domain.config["server"]["drain_timeout"] == 10
    assert Engine(domain, test_mode=True).drain_timeout == 10.0


def test_alert_callback_resolves_and_accepts_the_keyword_arguments(caplog):
    example = load_example("reference/server/hardening/001.py")
    example.domain.init(traverse=False)
    maintenance = Engine(example.domain, test_mode=True)._dlq_maintenance

    assert maintenance.alert_callback is example.on_dlq_alert

    # A callback whose parameters do not match the keyword names raises
    # TypeError, which the maintenance task logs as callback_failed.
    with caplog.at_level(logging.ERROR, logger="protean.server.dlq_maintenance"):
        maintenance._invoke_callback("orders:dlq", 150, 100)
    assert "dlq_maintenance.callback_failed" not in caplog.text


@pytest.mark.fastapi
def test_health_router_mounts_the_three_probe_paths():
    example = load_example("reference/server/hardening/001.py")
    example.domain.init(traverse=False)

    router = create_health_router(example.domain)
    assert {route.path for route in router.routes} == {
        "/healthz",
        "/livez",
        "/readyz",
    }

    app = FastAPI()
    app.include_router(create_health_router(example.domain, prefix="/ops"))
    client = TestClient(app)
    for path in ("/ops/healthz", "/ops/livez"):
        assert client.get(path).json() == {
            "status": "ok",
            "checks": {"application": "running"},
        }
    assert client.get("/ops/readyz").json()["status"] == "ok"
