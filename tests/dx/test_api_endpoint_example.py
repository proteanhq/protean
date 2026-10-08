"""The api-endpoint skill's app factory asset, driven over HTTP.

``test_examples.py`` only inits each asset. This harness builds the app with the
asset's own ``create_app`` and sends requests through ``TestClient``, so the
status codes and error bodies the skill teaches hold against the real
``protean.integrations.fastapi`` middleware and exception handlers.
"""

from __future__ import annotations

import runpy
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from protean import dx
from protean.domain import Domain

# This builds its own domain from package data; it never touches the autouse
# ``test_domain`` fixture, so skip it and its initialization cost.
pytestmark = pytest.mark.no_test_domain

PACK_ROOT = Path(str(dx.pack_files()))
ASSET = (
    PACK_ROOT
    / dx.SKILLS_DIR
    / "api-endpoint"
    / "assets"
    / "api_endpoint_complete_router.py"
)

# The asset is executed by path, so the pack must be unpacked on disk. CI
# installs unzipped, so this skips cleanly only in the zip case.
if not PACK_ROOT.is_dir():
    pytest.skip(
        "DX pack is not unpacked on disk; the api-endpoint asset is executed by path",
        allow_module_level=True,
    )


@pytest.fixture(scope="module")
def client() -> TestClient:
    namespace = runpy.run_path(str(ASSET), run_name="api_endpoint_complete_router")
    domains = [value for value in namespace.values() if isinstance(value, Domain)]
    assert len(domains) == 1, "the factory asset must define exactly one Domain"
    domain = domains[0]
    domain.init(traverse=False)
    return TestClient(namespace["create_app"](domain))


def _create(client: TestClient, shipment_id: str) -> None:
    response = client.post(
        "/shipments",
        json={
            "shipment_id": shipment_id,
            "origin": "NYC",
            "destination": "LAX",
            "weight": 25.5,
        },
    )
    assert response.status_code == 201, response.text


def test_create_returns_201_with_the_id(client):
    response = client.post(
        "/shipments",
        json={
            "shipment_id": "SHP-CREATE",
            "origin": "NYC",
            "destination": "LAX",
            "weight": 25.5,
        },
    )

    assert response.status_code == 201
    assert response.json() == {"shipment_id": "SHP-CREATE", "status": "created"}


def test_an_action_on_a_created_shipment_returns_200(client):
    _create(client, "SHP-TRACK")

    response = client.put(
        "/shipments/SHP-TRACK/tracking",
        json={"tracking_number": "TRACK-1", "carrier": "FedEx"},
    )

    assert response.status_code == 200
    assert response.json() == {"shipment_id": "SHP-TRACK", "status": "in_transit"}


def test_a_protean_validation_error_returns_400_keyed_by_field(client):
    # Both values pass the Pydantic model (a str and a float) and break the
    # command's own field rules, so the 400 comes from Protean, not FastAPI.
    response = client.post(
        "/shipments",
        json={
            "shipment_id": "SHP-BAD",
            "origin": "X" * 60,
            "destination": "LAX",
            "weight": -1.0,
        },
    )

    assert response.status_code == 400
    error = response.json()["error"]
    assert set(error) == {"origin", "weight"}
    for messages in error.values():
        assert isinstance(messages, list)
        assert messages
        assert all(isinstance(message, str) for message in messages)


def test_a_missing_shipment_returns_404(client):
    response = client.put("/shipments/SHP-NEVER-CREATED/deliver")

    assert response.status_code == 404
    assert "error" in response.json()


def test_a_wrong_state_returns_409(client):
    _create(client, "SHP-TWICE")
    first = client.put("/shipments/SHP-TWICE/cancel", json={"reason": "Moved"})
    assert first.status_code == 200

    second = client.put("/shipments/SHP-TWICE/cancel", json={"reason": "Moved"})

    assert second.status_code == 409
    assert "cancelled" in second.json()["error"]


def test_a_body_that_fails_the_pydantic_model_returns_fastapis_422(client):
    response = client.post(
        "/shipments",
        json={
            "shipment_id": "SHP-422",
            "origin": "NYC",
            "destination": "LAX",
            "weight": "heavy",
        },
    )

    assert response.status_code == 422
    body = response.json()
    assert "detail" in body
    assert "error" not in body
