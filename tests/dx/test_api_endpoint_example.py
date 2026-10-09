"""The api-endpoint skill's assets driven over HTTP, and the skill's text checks.

``test_examples.py`` only inits each asset. This harness builds the app with the
asset's own ``create_app`` and sends requests through ``TestClient``, so the
status codes and error bodies the skill teaches hold against the real
``protean.integrations.fastapi`` middleware and exception handlers. It also
checks what the skill states in prose: the ``protean[server]`` install, plain
``def`` endpoints, and no paths into Protean's own test folders.
"""

from __future__ import annotations

import ast
import re
import runpy
import uuid
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from protean import dx
from protean.domain import Domain
from protean.integrations.fastapi import (
    DomainContextMiddleware,
    register_exception_handlers,
)
from tests.support.snippets import extract_blocks

# This builds its own domain from package data; it never touches the autouse
# ``test_domain`` fixture, so skip it and its initialization cost.
pytestmark = pytest.mark.no_test_domain

PACK_ROOT = Path(str(dx.pack_files()))
SKILL_DIR = PACK_ROOT / dx.SKILLS_DIR / "api-endpoint"
ASSET = SKILL_DIR / "assets" / "api_endpoint_complete_router.py"
PATH_PARAMS_ASSET = SKILL_DIR / "assets" / "api_endpoint_path_params.py"
FASTAPI_GUIDE = Path(__file__).parents[2] / "docs" / "guides" / "fastapi" / "index.md"

# The asset is executed by path, so the pack must be unpacked on disk. CI
# installs unzipped, so this skips cleanly only in the zip case.
if not PACK_ROOT.is_dir():
    pytest.skip(
        "DX pack is not unpacked on disk; the api-endpoint asset is executed by path",
        allow_module_level=True,
    )


def _load(asset: Path) -> tuple[dict, Domain]:
    namespace = runpy.run_path(str(asset), run_name=asset.stem)
    domains = [value for value in namespace.values() if isinstance(value, Domain)]
    assert len(domains) == 1, f"{asset.name} must define exactly one Domain"
    domain = domains[0]
    domain.init(traverse=False)
    return namespace, domain


def _unique(prefix: str) -> str:
    # The module-scoped client keeps its store between tests, so each test
    # uses fresh ids and still passes when it is run again.
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


@pytest.fixture(scope="module")
def client() -> TestClient:
    namespace, domain = _load(ASSET)
    return TestClient(namespace["create_app"](domain))


@pytest.fixture(scope="module")
def path_params_client() -> TestClient:
    namespace, domain = _load(PATH_PARAMS_ASSET)
    app = FastAPI()
    app.add_middleware(DomainContextMiddleware, route_domain_map={"/": domain})
    register_exception_handlers(app)
    app.include_router(namespace["router"])
    return TestClient(app)


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
    shipment_id = _unique("SHP-CREATE")
    response = client.post(
        "/shipments",
        json={
            "shipment_id": shipment_id,
            "origin": "NYC",
            "destination": "LAX",
            "weight": 25.5,
        },
    )

    assert response.status_code == 201
    assert response.json() == {"shipment_id": shipment_id, "status": "created"}


def test_an_action_on_a_created_shipment_returns_200(client):
    shipment_id = _unique("SHP-TRACK")
    _create(client, shipment_id)

    response = client.put(
        f"/shipments/{shipment_id}/tracking",
        json={"tracking_number": "TRACK-1", "carrier": "FedEx"},
    )

    assert response.status_code == 200
    assert response.json() == {"shipment_id": shipment_id, "status": "in_transit"}


def test_a_protean_validation_error_returns_400_keyed_by_field(client):
    # Both values pass the Pydantic model (a str and a float) and break the
    # command's own field rules, so the 400 comes from Protean, not FastAPI.
    response = client.post(
        "/shipments",
        json={
            "shipment_id": _unique("SHP-BAD"),
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
    shipment_id = _unique("SHP-TWICE")
    _create(client, shipment_id)
    first = client.put(f"/shipments/{shipment_id}/cancel", json={"reason": "Moved"})
    assert first.status_code == 200

    second = client.put(f"/shipments/{shipment_id}/cancel", json={"reason": "Moved"})

    assert second.status_code == 409
    assert "cancelled" in second.json()["error"]


def test_a_body_that_fails_the_pydantic_model_returns_fastapis_422(client):
    response = client.post(
        "/shipments",
        json={
            "shipment_id": _unique("SHP-422"),
            "origin": "NYC",
            "destination": "LAX",
            "weight": "heavy",
        },
    )

    assert response.status_code == 422
    body = response.json()
    assert "detail" in body
    assert "error" not in body


def test_a_duplicate_id_returns_400_keyed_by_the_id_field(client):
    shipment_id = _unique("SHP-DUP")
    _create(client, shipment_id)

    response = client.post(
        "/shipments",
        json={
            "shipment_id": shipment_id,
            "origin": "NYC",
            "destination": "LAX",
            "weight": 25.5,
        },
    )

    assert response.status_code == 400
    assert list(response.json()["error"]) == ["shipment_id"]


def test_the_error_body_correlation_id_matches_the_response_header(client):
    response = client.put(
        f"/shipments/{_unique('SHP-NONE')}/deliver",
        headers={"X-Correlation-ID": "corr-api-endpoint"},
    )

    assert response.status_code == 404
    assert response.headers["X-Correlation-ID"] == "corr-api-endpoint"
    assert response.json()["correlation_id"] == "corr-api-endpoint"


def test_a_router_only_asset_returns_404_for_a_missing_order(path_params_client):
    response = path_params_client.put(
        f"/orders/{_unique('ORD-NONE')}/cancel", json={"reason": "Moved"}
    )

    assert response.status_code == 404
    assert "error" in response.json()


# --- What the skill states in prose ---


def _async_endpoints_calling_process(source: str) -> list[str]:
    """Names of ``async def`` functions that call ``.process(...)``."""
    return [
        node.name
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.AsyncFunctionDef)
        and any(
            isinstance(call, ast.Call)
            and isinstance(call.func, ast.Attribute)
            and call.func.attr == "process"
            for call in ast.walk(node)
        )
    ]


def _skill_sources() -> list[tuple[str, str]]:
    sources = [
        (str(path.relative_to(SKILL_DIR)), path.read_text(encoding="utf-8"))
        for path in sorted((SKILL_DIR / "assets").glob("*.py"))
    ]
    pages = [SKILL_DIR / "SKILL.md", *sorted((SKILL_DIR / "references").glob("*.md"))]
    for page in pages:
        for block in extract_blocks(page.read_text(encoding="utf-8")):
            if not block.fragment:
                label = f"{page.relative_to(SKILL_DIR)}:{block.line}"
                sources.append((label, block.source))
    return sources


def test_the_async_endpoint_check_flags_the_skills_wrong_example():
    wrong = [
        block
        for block in extract_blocks((SKILL_DIR / "SKILL.md").read_text("utf-8"))
        if block.fragment and "async def place_order" in block.source
    ]
    assert len(wrong) == 1

    assert _async_endpoints_calling_process(wrong[0].source) == ["place_order"]


def test_no_skill_endpoint_is_async_def_and_calls_process():
    sources = _skill_sources()
    assert len(sources) > 4

    offenders = {
        label: names
        for label, source in sources
        if (names := _async_endpoints_calling_process(source))
    }

    assert offenders == {}


def test_the_fastapi_guide_has_no_async_def_endpoint_calling_process():
    blocks = extract_blocks(FASTAPI_GUIDE.read_text(encoding="utf-8"))
    assert blocks

    offenders = {
        block.line: names
        for block in blocks
        if (names := _async_endpoints_calling_process(block.source))
    }

    assert offenders == {}


def test_the_skill_says_fastapi_comes_with_the_server_extra():
    text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")

    assert 'pip install "protean[server]"' in text


def test_no_skill_page_points_at_protean_test_folders():
    # ``# tests/conftest.py`` names a file in the reader's own project.
    allowed = "# tests/conftest.py"
    files = sorted(
        path for path in SKILL_DIR.rglob("*") if path.suffix in {".md", ".py"}
    )
    assert files

    hits = [
        f"{path.relative_to(SKILL_DIR)}: {line.strip()}"
        for path in files
        for line in path.read_text(encoding="utf-8").splitlines()
        if re.search(r"\btests/", line) and line.strip() != allowed
    ]

    assert hits == []
