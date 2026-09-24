"""The currency rule in the generate-test-scaffold aggregate asset.

``test_examples.py`` inits every asset and sweeps them for orphaned value
objects; it never runs one. ``scaffold_aggregate_unit.py`` needs more than that,
because two of its parts have to agree: ``Money.add()`` refuses to add across
currencies, while ``Order.total`` sums the item amounts. An order holding both
USD and EUR items would make the aggregate contradict its own value object and
report a meaningless total.

The asset answers that by keeping the currency out of ``add_item`` entirely, so
the documented path cannot build a mixed order, and by carrying an invariant for
an order assembled by hand. These tests pin both halves.
"""

from __future__ import annotations

import inspect
import runpy
from pathlib import Path
from typing import Any

import pytest

from protean import dx
from protean.domain import Domain
from protean.exceptions import ValidationError

# Builds a domain directly from package data; never touches the autouse
# ``test_domain`` fixture, so skip it and its initialization cost.
pytestmark = pytest.mark.no_test_domain

PACK_ROOT = Path(str(dx.pack_files()))
ASSET = (
    PACK_ROOT
    / dx.SKILLS_DIR
    / "generate-test-scaffold"
    / "assets"
    / "scaffold_aggregate_unit.py"
)

# The runner executes the asset by path, so it needs the pack unpacked on disk.
# The accessor does not promise a filesystem root (a zip install would not have
# one); CI installs unzipped, so this skips cleanly only in the zip case.
if not PACK_ROOT.is_dir():
    pytest.skip(
        "DX pack is not unpacked on disk; the asset is executed by path",
        allow_module_level=True,
    )


@pytest.fixture(scope="module")
def asset() -> tuple[dict[str, Any], Domain]:
    """Run the asset under its own run_name and init its domain."""
    namespace = runpy.run_path(str(ASSET), run_name="scaffold_aggregate_unit_test")
    domains = [value for value in namespace.values() if isinstance(value, Domain)]
    assert len(domains) == 1, "the asset must define exactly one Domain"
    domain = domains[0]
    domain.init(traverse=False)
    return namespace, domain


def test_add_item_takes_no_currency(asset):
    """The structural half: the documented path cannot build a mixed order.

    A ``currency`` argument here would let one order hold USD and EUR items
    while ``total`` summed their bare amounts.
    """
    namespace, _ = asset
    parameters = inspect.signature(namespace["Order"].add_item).parameters

    assert "currency" not in parameters
    assert list(parameters) == ["self", "product_id", "quantity", "unit_price"]


def test_the_documented_calls_still_total_correctly(asset):
    """``SKILL.md`` and ``references/aggregate-tests.md`` make exactly these
    calls and assert this total, so the embedded ``Money`` must not break them."""
    namespace, domain = asset
    with domain.domain_context():
        order = namespace["Order"].create(customer_id="c-1")
        order.add_item(product_id="p-1", quantity=2, unit_price=10.0)
        order.add_item(product_id="p-2", quantity=1, unit_price=25.0)

        assert order.total == 45.0
        assert order.line_items[0].unit_price.currency == "USD"
        assert order.line_items[0].subtotal == 20.0


def test_the_invariant_rejects_an_order_assembled_by_hand(asset):
    """The remaining path: building the items directly, around ``add_item``."""
    namespace, domain = asset
    with domain.domain_context(), pytest.raises(ValidationError) as error:
        order = namespace["Order"].create(customer_id="c-2")
        order.add_line_items(
            namespace["LineItem"](
                product_id="p-1",
                quantity=1,
                unit_price=namespace["Money"](amount=10.0, currency="EUR"),
            )
        )
        order.add_line_items(
            namespace["LineItem"](
                product_id="p-2",
                quantity=1,
                unit_price=namespace["Money"](amount=10.0, currency="USD"),
            )
        )

    assert "line_items" in error.value.messages


def test_money_still_refuses_to_add_across_currencies(asset):
    """The rule the aggregate has to stay consistent with."""
    namespace, domain = asset
    with domain.domain_context():
        usd = namespace["Money"](amount=10.0, currency="USD")
        eur = namespace["Money"](amount=10.0, currency="EUR")

        assert usd.add(namespace["Money"](amount=20.0)).amount == 30.0
        with pytest.raises(ValueError, match="Cannot add USD and EUR"):
            usd.add(eur)
