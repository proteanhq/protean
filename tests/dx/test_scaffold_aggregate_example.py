"""The currency rule in the generate-test-scaffold aggregate asset.

``test_examples.py`` inits every asset and sweeps them for orphaned value
objects; it never runs one. ``scaffold_aggregate_unit.py`` needs more than that,
because two of its parts have to agree: ``Money.add()`` refuses to add across
currencies, while ``Order.total`` sums the item amounts. An order holding both
USD and EUR items would make the aggregate contradict its own value object and
report a meaningless total.

The asset answers that by keeping the currency out of ``add_item`` entirely, so
the documented path cannot build a mixed order, and by folding the prices with
``Money.add()`` in ``total``, so an order assembled by hand cannot produce one
either. An ``@invariant.post`` cannot carry the second half: ``HasMany.add()``
caches the item and then calls ``_postcheck()``, and it does not undo the cache
when the check raises, so a caller who catches the error still holds the item
the rule rejected and can still save the order. These tests pin both halves,
including that last part.
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

        assert order.total.amount == 45.0
        assert order.total.currency == "USD"
        assert order.line_items[0].unit_price.currency == "USD"
        assert order.line_items[0].subtotal == 20.0


def test_a_mixed_order_assembled_by_hand_cannot_produce_a_total(asset):
    """The remaining path: building the items directly, around ``add_item``.

    The fold is what stops it. Adding the second item does not raise, so an
    invariant that reported here would leave the order holding it anyway.
    """
    namespace, domain = asset
    with domain.domain_context():
        order = namespace["Order"].create(customer_id="c-2")
        for product_id, currency in (("p-1", "EUR"), ("p-2", "USD")):
            order.add_line_items(
                namespace["LineItem"](
                    product_id=product_id,
                    quantity=1,
                    unit_price=namespace["Money"](amount=10.0, currency=currency),
                )
            )

        assert len(order.line_items) == 2
        with pytest.raises(ValueError, match="Cannot add EUR and USD"):
            order.total


def test_a_single_currency_order_totals_in_that_currency(asset):
    """The fold starts from the first item, so a EUR-only order totals in EUR
    instead of failing against a USD zero."""
    namespace, domain = asset
    with domain.domain_context():
        order = namespace["Order"].create(customer_id="c-3")
        order.add_line_items(
            namespace["LineItem"](
                product_id="p-1",
                quantity=2,
                unit_price=namespace["Money"](amount=7.5, currency="EUR"),
            )
        )

        assert order.total.amount == 15.0
        assert order.total.currency == "EUR"


def test_an_empty_order_totals_zero(asset):
    namespace, domain = asset
    with domain.domain_context():
        assert namespace["Order"].create(customer_id="c-4").total.amount == 0.0


def test_place_builds_the_event_before_it_changes_status(asset):
    """`total` can refuse, so reading it after the status changed would leave
    the order placed with no event and no way to retry."""
    namespace, domain = asset
    with domain.domain_context():
        order = namespace["Order"].create(customer_id="c-5")
        for product_id, currency in (("p-1", "USD"), ("p-2", "EUR")):
            order.add_line_items(
                namespace["LineItem"](
                    product_id=product_id,
                    quantity=1,
                    unit_price=namespace["Money"](amount=10.0, currency=currency),
                )
            )

        with pytest.raises(ValueError, match="Cannot add USD and EUR"):
            order.place()

        assert order.status == "draft"
        assert order._events == []

        # Still placeable once the order holds one currency again.
        order.remove_item("p-2")
        order.place()
        assert order.status == "placed"
        assert [type(event).__name__ for event in order._events] == ["OrderPlaced"]


@pytest.mark.parametrize("reason", ["", None])
def test_cancel_builds_the_event_before_it_changes_status(asset, reason):
    """`reason` is required, so the event rejects an empty one. Building it
    after the status changed left the order cancelled with no event."""
    namespace, domain = asset
    with domain.domain_context():
        order = namespace["Order"].create(customer_id="c-6")
        order.add_item(product_id="p-1", quantity=1, unit_price=5.0)
        order.place()
        order._events.clear()

        with pytest.raises(ValidationError):
            order.cancel(reason=reason)

        assert order.status == "placed"
        assert order._events == []

        order.cancel(reason="changed their mind")
        assert order.status == "cancelled"
        assert [type(event).__name__ for event in order._events] == ["OrderCancelled"]


def test_money_still_refuses_to_add_across_currencies(asset):
    """The rule the aggregate has to stay consistent with."""
    namespace, domain = asset
    with domain.domain_context():
        usd = namespace["Money"](amount=10.0, currency="USD")
        eur = namespace["Money"](amount=10.0, currency="EUR")

        assert usd.add(namespace["Money"](amount=20.0)).amount == 30.0
        with pytest.raises(ValueError, match="Cannot add USD and EUR"):
            usd.add(eur)
