"""The examples on the production deployment guide behave as the page says."""

import pytest
from fastapi.testclient import TestClient

from tests.docs.support import load_example

pytestmark = pytest.mark.no_test_domain


@pytest.mark.fastapi
def test_api_app_serves_the_liveness_and_readiness_paths():
    example = load_example("guides/server/production-deployment/001.py")
    example.domain.init(traverse=False)

    client = TestClient(example.app)

    assert client.get("/livez").status_code == 200
    readiness = client.get("/readyz")
    assert readiness.status_code == 200
    assert readiness.json()["status"] == "ok"
    checks = readiness.json()["checks"]
    assert set(checks) == {"providers", "brokers", "caches", "event_store"}
    assert checks["providers"]["default"] == "ok"
    assert checks["event_store"] == "ok"
    assert client.get("/startupz").status_code == 404
