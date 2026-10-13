"""The examples on ``docs/reference/server/observability.md`` behave as the page says."""

import shutil

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from protean import Domain
from tests.docs.support import DOCS_SRC, load_example

pytestmark = pytest.mark.no_test_domain

RETENTION_TOML = DOCS_SRC / "reference/server/observability/observatory.toml"


@pytest.mark.fastapi
def test_create_observatory_app_serves_both_domains():
    example = load_example("reference/server/observability/001.py")

    assert isinstance(example.app, FastAPI)
    assert example.app.title == "Protean Observatory"

    # The health endpoint lists every domain the app was built with. With the
    # default inline broker there is no Redis, so the status is not "ok".
    body = TestClient(example.app).get("/api/health").json()
    assert body["domains"] == ["identity", "catalogue"]
    assert body["infrastructure"]["redis"]["healthy"] is False


@pytest.mark.fastapi
def test_observatory_allows_only_the_configured_cors_origin():
    example = load_example("reference/server/observability/002.py")
    client = TestClient(example.observatory.app)

    allowed = client.get(
        "/api/health", headers={"Origin": "https://monitoring.example.com"}
    )
    other = client.get("/api/health", headers={"Origin": "https://other.example.com"})

    assert example.observatory.cors_origins == ["https://monitoring.example.com"]
    assert (
        allowed.headers["access-control-allow-origin"]
        == "https://monitoring.example.com"
    )
    assert "access-control-allow-origin" not in other.headers


def test_trace_retention_days_sets_how_long_traces_persist(tmp_path):
    shutil.copy(RETENTION_TOML, tmp_path / "domain.toml")
    domain = Domain(root_path=str(tmp_path), name="Monitoring")

    assert domain.config["observatory"]["trace_retention_days"] == 7
    emitter = domain.trace_emitter
    assert emitter._persist is True
    assert emitter._retention_ms == 7 * 86_400_000


def test_zero_trace_retention_days_turns_persistence_off(tmp_path):
    text = RETENTION_TOML.read_text().replace(
        "trace_retention_days = 7", "trace_retention_days = 0"
    )
    (tmp_path / "domain.toml").write_text(text)
    domain = Domain(root_path=str(tmp_path), name="Monitoring")

    assert domain.trace_emitter._persist is False
