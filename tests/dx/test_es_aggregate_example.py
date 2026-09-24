"""Replay behaviour of the event-sourced-aggregate asset.

``test_examples.py`` only inits each asset; it never replays one. The currency
rule in ``es_aggregate_with_entities.py`` needs more than that, because an
aggregate invariant cannot enforce it during replay: ``from_events()`` sets
``_disable_invariant_checks`` for the whole replay (``core/aggregate.py``), so
a post-invariant never runs there.

The asset answers that by putting the currency on the order rather than on each
item, so ``ItemAdded`` cannot describe a per-item currency and a stream cannot
describe a mixed order. These tests pin that shape: the event has no currency
field, replay prices every item in the order's currency, and the invariant that
remains still nets an order assembled by hand.

The same file has a second rule of the same kind. ``raise_()`` appends the event
and then runs the apply handler, so a constraint that lives only on ``LineItem``
is checked after the event is already pending: the caller sees the error and a
rejected ``ItemAdded`` sits in ``_events`` waiting to be saved. ``ItemAdded``
therefore carries the same constraints as the item it describes, and these tests
pin that no rejected event is ever left pending.
"""

from __future__ import annotations

import runpy
import uuid
from pathlib import Path
from typing import Any

import pytest

from protean import dx
from protean.domain import Domain
from protean.exceptions import ValidationError
from protean.utils.reflection import declared_fields

# Builds a domain directly from package data; never touches the autouse
# ``test_domain`` fixture, so skip it and its initialization cost.
pytestmark = pytest.mark.no_test_domain

PACK_ROOT = Path(str(dx.pack_files()))
ASSET = (
    PACK_ROOT
    / dx.SKILLS_DIR
    / "event-sourced-aggregate"
    / "assets"
    / "es_aggregate_with_entities.py"
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
    namespace = runpy.run_path(str(ASSET), run_name="es_aggregate_with_entities_test")
    domains = [value for value in namespace.values() if isinstance(value, Domain)]
    assert len(domains) == 1, "the asset must define exactly one Domain"
    domain = domains[0]
    domain.init(traverse=False)
    return namespace, domain


def _item_added(namespace, order_id, **kwargs):
    return namespace["ItemAdded"](
        order_id=order_id, item_id=str(uuid.uuid4()), **kwargs
    )


def test_item_added_cannot_carry_a_currency(asset):
    """The structural guarantee: a stream cannot describe a mixed order.

    If a per-item ``currency`` field ever comes back, replay can rebuild an
    order whose items disagree, and no invariant will catch it.
    """
    namespace, _ = asset
    assert "currency" not in declared_fields(namespace["ItemAdded"])
    assert "currency" in declared_fields(namespace["OrderCreated"])
    assert "currency" in declared_fields(namespace["Order"])


def test_replay_prices_every_item_in_the_order_currency(asset):
    namespace, domain = asset
    with domain.domain_context():
        order = namespace["Order"].from_events(
            [
                namespace["OrderCreated"](
                    order_id="ORD-R1", customer_id="C1", currency="EUR"
                ),
                _item_added(
                    namespace, "ORD-R1", product_id="A", quantity=2, unit_price=100.0
                ),
                _item_added(
                    namespace, "ORD-R1", product_id="B", quantity=1, unit_price=50.0
                ),
            ]
        )

    assert [item.unit_price.currency for item in order.items] == ["EUR", "EUR"]
    assert order.total.amount == 250.0
    assert order.total.currency == "EUR"


def test_the_entity_rejects_a_price_below_the_minimum(asset):
    """The price rule sits on ``LineItem``, which replay constructs directly, so
    it holds where an aggregate invariant would not. Checked on the entity
    itself, because ``ItemAdded`` can no longer express a price this low."""
    namespace, domain = asset
    with domain.domain_context(), pytest.raises(ValidationError) as error:
        namespace["LineItem"](
            item_id=str(uuid.uuid4()),
            product_id="Z",
            quantity=1,
            unit_price=namespace["Money"](amount=0.0, currency="USD"),
        )

    assert "unit_price" in error.value.messages


@pytest.mark.parametrize(
    ("label", "kwargs"),
    [
        ("a price of zero", {"unit_price": 0.0}),
        ("a negative price", {"unit_price": -5.0}),
        ("a quantity of zero", {"quantity": 0}),
        ("an over-long product id", {"product_id": "X" * 60}),
        # 250 characters: inside the 255 a bare String() allows by default, so
        # this case only passes while ItemAdded declares max_length=200 itself.
        ("an over-long description", {"description": "D" * 250}),
    ],
)
def test_an_invalid_item_leaves_no_event_pending(asset, label, kwargs):
    """Every constraint on ``LineItem`` is also on ``ItemAdded``, so an invalid
    call fails while the event is built and ``raise_()`` is never reached.

    Without this the event is appended first and the constraint is checked
    afterwards. The caller sees the error and moves on, and the rejected event
    is still in ``_events``: saving the order then persists it.
    """
    namespace, domain = asset
    with domain.domain_context():
        order = namespace["Order"].create(order_id=f"ORD-P-{label}", customer_id="C")
        pending_before = len(order._events)

        with pytest.raises(ValidationError):
            order.add_item(**{"product_id": "P", "unit_price": 10.0, **kwargs})

        assert len(order._events) == pending_before, (
            f"{label} left a rejected ItemAdded pending"
        )
        assert len(order.items) == 0


def test_the_invariant_nets_an_order_assembled_by_hand(asset):
    """Outside replay the invariant does run, so it still guards the rule."""
    namespace, domain = asset
    with domain.domain_context(), pytest.raises(ValidationError) as error:
        order = namespace["Order"](order_id="ORD-R3", customer_id="C3", currency="USD")
        order.add_items(
            namespace["LineItem"](
                item_id=str(uuid.uuid4()),
                product_id="X",
                quantity=1,
                unit_price=namespace["Money"](amount=5.0, currency="EUR"),
            )
        )

    assert "items" in error.value.messages


def test_the_front_door_totals_in_the_order_currency(asset):
    namespace, domain = asset
    with domain.domain_context():
        order = namespace["Order"].create(
            order_id="ORD-R4",
            customer_id="C4",
            currency="GBP",
            items=[{"product_id": "P", "unit_price": 10.0, "quantity": 3}],
        )

    assert order.total.amount == 30.0
    assert order.total.currency == "GBP"
