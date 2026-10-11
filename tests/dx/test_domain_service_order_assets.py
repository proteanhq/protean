"""The domain-service skill's order assets check stock per product.

Two order lines for the same product draw on the same stock, so each service
checks their total against it.
"""

from __future__ import annotations

import itertools
import runpy
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from protean import dx
from protean.exceptions import ValidationError

pytestmark = pytest.mark.no_test_domain

PACK_ROOT = Path(str(dx.pack_files()))
ASSETS = PACK_ROOT / dx.SKILLS_DIR / "domain-service" / "assets"

if not PACK_ROOT.is_dir():
    pytest.skip(
        "DX pack is not unpacked on disk; the assets are executed by path",
        allow_module_level=True,
    )

_run_names = itertools.count()

Place = Callable[[dict[str, Any], Any, list[Any]], Any]

# Each asset's service, called the way its docstring shows.
ASSETS_AND_CALLS: dict[str, Place] = {
    "domain_service_callable.py": lambda ns, order, stock: ns["place_order"](
        order, stock
    )(),
    "domain_service_instance_methods.py": lambda ns, order, stock: ns[
        "OrderPlacementService"
    ](order, stock).place_order(),
    "domain_service_class_methods.py": lambda ns, order, stock: ns[
        "OrderPlacementService"
    ].place_order(order, stock),
    "domain_service_with_invariants.py": lambda ns, order, stock: ns[
        "OrderPlacementService"
    ](order, stock)(),
}


@pytest.fixture(params=sorted(ASSETS_AND_CALLS))
def asset(request) -> Any:
    ns = runpy.run_path(
        str(ASSETS / request.param), run_name=f"_order_asset_{next(_run_names)}_"
    )
    domain = ns["domain"]
    domain.init(traverse=False)
    with domain.domain_context():
        yield ns, ASSETS_AND_CALLS[request.param]


def _order(ns: dict[str, Any], *quantities: int) -> Any:
    return ns["Order"](
        customer_id="c-1",
        payment_id="p-1",
        items=[
            ns["OrderItem"](product_id="P", quantity=q, price=1.0) for q in quantities
        ],
    )


def _stock(ns: dict[str, Any], quantity: int) -> list[Any]:
    return [ns["Inventory"](product_id="P", quantity=quantity)]


def test_two_lines_for_one_product_cannot_exceed_its_stock(asset):
    ns, place = asset
    order = _order(ns, 3, 3)

    with pytest.raises(ValidationError) as exc:
        place(ns, order, _stock(ns, 4))

    assert exc.value.messages == {"_service": ["Product is out of stock"]}
    assert order.status == ns["OrderStatus"].PENDING.value


def test_two_lines_within_the_stock_confirm_the_order(asset):
    ns, place = asset
    order = _order(ns, 3, 1)

    place(ns, order, _stock(ns, 4))

    assert order.status == ns["OrderStatus"].CONFIRMED.value
    [confirmed] = [e for e in order._events if isinstance(e, ns["OrderConfirmed"])]
    assert [(i["product_id"], i["quantity"]) for i in confirmed.items] == [
        ("P", 3),
        ("P", 1),
    ]
