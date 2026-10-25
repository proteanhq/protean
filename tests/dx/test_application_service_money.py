"""The application-service error-handling asset totals an order exactly.

``Order.total_amount`` is a ``Decimal`` with four places. The factory sums the
item amounts, so floats such as 0.10 and 0.20 would sum to
0.30000000000000004 and fail the field. The asset takes decimal amounts, and
these tests check that the total of fractional amounts is exact.
"""

from __future__ import annotations

import runpy
from decimal import Decimal as D
from pathlib import Path

import pytest

from protean import dx
from protean.exceptions import ValidationError

pytestmark = pytest.mark.no_test_domain

ASSET = (
    Path(str(dx.pack_files()))
    / dx.SKILLS_DIR
    / "application-service"
    / "assets"
    / "application_service_error_handling.py"
)

if not ASSET.is_file():
    pytest.skip(
        "DX pack is not unpacked on disk; the asset is executed by path",
        allow_module_level=True,
    )


@pytest.fixture
def asset() -> dict:
    ns = runpy.run_path(str(ASSET), run_name="_application_service_money_")
    ns["domain"].init(traverse=False)
    return ns


def test_fractional_amounts_total_exactly(asset):
    with asset["domain"].domain_context():
        svc = asset["OrderApplicationServices"]()
        order_id = svc.place_order(customer_id="CUST-1", items=[D("0.10"), D("0.20")])

        order = asset["domain"].repository_for(asset["Order"]).get(order_id)
        assert order.total_amount == D("0.30")
        assert order.item_count == 2


def test_an_order_without_items_is_rejected(asset):
    with asset["domain"].domain_context():
        svc = asset["OrderApplicationServices"]()
        with pytest.raises(ValidationError) as exc:
            svc.place_order(customer_id="CUST-1", items=[])

        assert exc.value.messages == {"items": ["Order must have at least one item"]}


def test_the_demo_runs_with_decimal_amounts():
    runpy.run_path(str(ASSET), run_name="__main__")
