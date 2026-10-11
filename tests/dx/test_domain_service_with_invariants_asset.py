"""The domain-service skill's invariants asset checks stock per product.

Two order lines for the same product draw on the same stock, so the service
checks their total against it.
"""

from __future__ import annotations

import itertools
import runpy
from pathlib import Path
from typing import Any

import pytest

from protean import dx
from protean.exceptions import ValidationError

pytestmark = pytest.mark.no_test_domain

PACK_ROOT = Path(str(dx.pack_files()))
ASSET = (
    PACK_ROOT
    / dx.SKILLS_DIR
    / "domain-service"
    / "assets"
    / "domain_service_with_invariants.py"
)

if not PACK_ROOT.is_dir():
    pytest.skip(
        "DX pack is not unpacked on disk; the asset is executed by path",
        allow_module_level=True,
    )

_run_names = itertools.count()


@pytest.fixture
def ns() -> Any:
    namespace = runpy.run_path(
        str(ASSET), run_name=f"_with_invariants_{next(_run_names)}_"
    )
    domain = namespace["domain"]
    domain.init(traverse=False)
    with domain.domain_context():
        yield namespace


def _order(ns: dict[str, Any], *quantities: int) -> Any:
    return ns["Order"](
        customer_id="c-1",
        payment_id="p-1",
        items=[ns["OrderItem"](product_id="P", quantity=q) for q in quantities],
    )


def _stock(ns: dict[str, Any], quantity: int) -> list[Any]:
    return [ns["Inventory"](product_id="P", quantity=quantity)]


def test_two_lines_for_one_product_cannot_exceed_its_stock(ns):
    order = _order(ns, 3, 3)

    with pytest.raises(ValidationError) as exc:
        ns["OrderPlacementService"](order, _stock(ns, 4))()

    assert exc.value.messages == {"_service": ["Product is out of stock"]}
    assert order.status == ns["OrderStatus"].PENDING.value


def test_two_lines_within_the_stock_confirm_the_order(ns):
    order = _order(ns, 3, 1)

    ns["OrderPlacementService"](order, _stock(ns, 4))()

    assert order.status == ns["OrderStatus"].CONFIRMED.value
    [confirmed] = [e for e in order._events if isinstance(e, ns["OrderConfirmed"])]
    assert confirmed.items == [
        {"product_id": "P", "quantity": 3},
        {"product_id": "P", "quantity": 1},
    ]
