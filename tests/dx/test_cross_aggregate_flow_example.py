"""The event-handler cross-sync asset: the diagnostics, and the flow.

``test_asset_diagnostics.py`` proves the asset reports no
``EVENT_HANDLER_FOREIGN_EVENT``, but a clean ``check`` does not prove the flow
works. This harness runs it:

- Shipping an order reduces the product's stock through a domain event and a
  command, so the asset's claim that Inventory changes when Order ships holds.
- Redelivering the event, because delivery is at least once, leaves the stock
  where the first delivery put it.
- The event handler sits in the cluster that owns the event, and the asset
  carries no warning-level diagnostics of its own.

The runner mirrors ``test_split_aggregate_example.py``: each test executes the
asset under its own ``run_name`` so registrations cannot collide.
"""

from __future__ import annotations

import runpy
from pathlib import Path
from typing import Any

import pytest

from protean import dx
from protean.domain import Domain
from protean.ir.builder import IRBuilder

pytestmark = pytest.mark.no_test_domain

PACK_ROOT = Path(str(dx.pack_files()))
ASSET = (
    PACK_ROOT
    / dx.SKILLS_DIR
    / "event-handler"
    / "assets"
    / "cross_sync_order_inventory.py"
)

if not PACK_ROOT.is_dir():
    pytest.skip(
        "DX pack is not unpacked on disk; the cross-sync asset is executed by path",
        allow_module_level=True,
    )


def _load(run_name: str) -> tuple[dict[str, Any], Domain]:
    """Run the asset and return its namespace and its initialized domain."""
    namespace = runpy.run_path(str(ASSET), run_name=run_name)
    domains = [value for value in namespace.values() if isinstance(value, Domain)]
    assert len(domains) == 1, "the asset must define exactly one Domain"
    domain = domains[0]
    domain.init(traverse=False)
    return namespace, domain


def _ship_one_order(namespace: dict[str, Any], domain: Domain) -> str:
    """Seed ten units of SKU-1, ship an order for three, and return its id."""
    domain.repository_for(namespace["Inventory"]).add(
        namespace["Inventory"](product_id="SKU-1", stock_level=10)
    )
    order = namespace["Order"](product_id="SKU-1", quantity=3)
    domain.repository_for(namespace["Order"]).add(order)
    domain.process(namespace["ShipOrder"](order_id=order.id))
    return order.id


def _stock(namespace: dict[str, Any], domain: Domain) -> int:
    inventory = domain.repository_for(namespace["Inventory"])._dao.find_by(
        product_id="SKU-1"
    )
    return inventory.stock_level


def test_shipping_an_order_reduces_stock():
    namespace, domain = _load("_cross_sync_run_")

    with domain.domain_context():
        order_id = _ship_one_order(namespace, domain)
        order = domain.repository_for(namespace["Order"]).get(order_id)

        assert order.status == "shipped"
        assert _stock(namespace, domain) == 7


def test_a_redelivered_event_reduces_stock_once():
    """A restarted subscription can deliver OrderShipped again. The command
    carries the order id from the event, and Inventory's command handler skips
    an order it has already applied, so the stock drops once."""
    namespace, domain = _load("_cross_sync_redeliver_")

    with domain.domain_context():
        order_id = _ship_one_order(namespace, domain)
        assert _stock(namespace, domain) == 7

        # Redeliver the same event straight to the handler.
        namespace["InventorySyncHandler"]().on_order_shipped(
            namespace["OrderShipped"](order_id=order_id, product_id="SKU-1", quantity=3)
        )

        assert _stock(namespace, domain) == 7


def test_a_second_order_still_reduces_stock():
    """The guard skips only an order already applied. A different order for the
    same product must still reduce the stock."""
    namespace, domain = _load("_cross_sync_second_")

    with domain.domain_context():
        _ship_one_order(namespace, domain)
        order = namespace["Order"](product_id="SKU-1", quantity=2)
        domain.repository_for(namespace["Order"]).add(order)
        domain.process(namespace["ShipOrder"](order_id=order.id))

        assert _stock(namespace, domain) == 5


def test_the_handler_sits_in_the_cluster_that_owns_the_event():
    namespace, _ = _load("_cross_sync_owner_")

    handler = namespace["InventorySyncHandler"]
    event = namespace["OrderShipped"]
    assert handler.meta_.part_of is namespace["Order"]
    assert event.meta_.part_of is namespace["Order"]


def test_the_asset_reports_no_warnings():
    _, domain = _load("_cross_sync_diagnostics_")
    ir = IRBuilder(domain).build()

    assert [
        d for d in ir["diagnostics"] if d["code"] == "EVENT_HANDLER_FOREIGN_EVENT"
    ] == []
    assert [
        (d["code"], d["element"])
        for d in ir["diagnostics"]
        if d["level"] in ("warning", "error")
    ] == []
