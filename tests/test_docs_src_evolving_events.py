"""Verify the runnable examples embedded in `docs/guides/evolving-events.md`.

The guide includes these modules via `--8<--` snippets; this test proves they
import cleanly, initialize, and that the upcaster chain actually transforms an
old payload — so the "working examples" in the guide stay working.
"""

import importlib.util
import os
from types import ModuleType

import pytest

_DOCS_SRC = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../docs_src/guides/evolving-events")
)


def _load(name: str) -> ModuleType:
    path = os.path.join(_DOCS_SRC, f"{name}.py")
    spec = importlib.util.spec_from_file_location(f"evolving_events_{name}", path)
    assert spec is not None and spec.loader is not None, f"cannot load {path}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.no_test_domain
def test_v1_baseline_initializes():
    v1 = _load("001")
    v1.domain.init(traverse=False)
    ir = v1.domain.to_ir()
    events = next(iter(ir["clusters"].values()))["events"]
    placed = next(e for e in events.values() if e["name"] == "OrderPlaced")
    assert placed["__version__"] == 1
    assert set(placed["fields"]) == {"order_id", "amount", "customer_name"}


@pytest.mark.no_test_domain
def test_v3_domain_has_evolution_surface():
    v3 = _load("002")
    v3.domain.init(traverse=False)
    ir = v3.domain.to_ir()

    # The upcaster chain the catalog/verdict rely on.
    assert ir["upcasters"] == {
        "OrderPlaced": [
            {"from_version": 1, "to_version": 2},
            {"from_version": 2, "to_version": 3},
        ]
    }

    events = next(iter(ir["clusters"].values()))["events"]
    placed = next(e for e in events.values() if e["name"] == "OrderPlaced")
    assert placed["__version__"] == 3
    assert placed["fields"]["customer"]["renamed_from"] == ["customer_name"]

    created = next(e for e in events.values() if e["name"] == "OrderCreated")
    assert created["deprecated"] == {"since": "0.16", "removal": "0.19"}
    assert created["superseded_by"] == "OrderPlaced"


@pytest.mark.no_test_domain
def test_upcaster_chain_transforms_a_v1_payload():
    v3 = _load("002")
    v1_to_v2 = v3.OrderPlacedV1toV2()
    v2_to_v3 = v3.OrderPlacedV2toV3()

    # A payload as written under v1 (with the old `customer_name`).
    payload = {"order_id": "o-1", "amount": 100, "customer_name": "Ada"}
    upcast = v2_to_v3.upcast(v1_to_v2.upcast(dict(payload)))

    assert upcast["customer"] == "Ada"  # renamed
    assert "customer_name" not in upcast
    assert upcast["currency"] == "USD"  # defaulted by the upcaster
    assert upcast["placed_at"] is None  # added in v3
