"""The Observatory on the monitoring guide serves the endpoints the page lists."""

import pytest
from fastapi.testclient import TestClient

from tests.docs.support import load_example

pytestmark = [pytest.mark.no_test_domain, pytest.mark.fastapi]


@pytest.fixture
def client():
    example = load_example("guides/server/monitoring/001.py")
    example.domain.init(traverse=False)
    return TestClient(example.observatory.app)


def test_the_health_endpoint_reports_the_domains_it_watches(client):
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json()["domains"] == ["Shop"]


def test_the_outbox_endpoint_counts_messages_per_domain(client):
    response = client.get("/api/outbox")

    assert response.status_code == 200
    assert response.json()["Shop"]["counts"]["pending"] == 0


@pytest.mark.parametrize(
    "path", ["/", "/api/streams", "/api/stats", "/api/subscriptions"]
)
def test_the_listed_endpoints_answer(client, path):
    assert client.get(path).status_code == 200


def test_the_metrics_endpoint_serves_prometheus_text(client):
    response = client.get("/metrics")

    assert response.status_code == 200
    assert "# TYPE protean_broker_up gauge" in response.text
    assert "protean_broker_up 1" in response.text


def test_an_endpoint_the_page_does_not_list_is_not_found(client):
    assert client.get("/api/unknown").status_code == 404
