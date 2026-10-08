"""The examples on the event sourcing pathway behave as the page says."""

import pytest

from protean.exceptions import IncorrectUsageError
from protean.fields import Identifier
from tests.docs.support import load_example

pytestmark = pytest.mark.no_test_domain


def test_place_applies_order_placed_to_the_order():
    example = load_example("guides/pathways/event-sourcing/001.py")
    example.domain.init(traverse=False)

    with example.domain.domain_context():
        order = example.Order(total=25.0)
        order.place()

    assert order.status == "placed"
    assert order.total == 25.0


def test_order_rebuilds_its_state_from_its_events():
    example = load_example("guides/pathways/event-sourcing/001.py")
    example.domain.init(traverse=False)

    with example.domain.domain_context():
        order = example.Order(total=25.0)
        order.place()
        order.raise_(example.OrderCancelled(order_id=order.id))

        rebuilt = example.Order.from_events(order._events)

    assert rebuilt.id == order.id
    assert rebuilt.status == "cancelled"
    assert rebuilt.total == 25.0


def test_repository_replays_the_events_when_it_loads_the_order():
    example = load_example("guides/pathways/event-sourcing/001.py")
    example.domain.init(traverse=False)

    with example.domain.domain_context():
        order = example.Order(total=40.0)
        order.place()
        repo = example.domain.repository_for(example.Order)
        repo.add(order)

        loaded = repo.get(order.id)

    assert loaded.id == order.id
    assert loaded.status == "placed"
    assert loaded.total == 40.0


def test_raising_an_event_without_an_apply_handler_fails():
    example = load_example("guides/pathways/event-sourcing/001.py")

    @example.domain.event(part_of=example.Order)
    class OrderShipped:
        order_id = Identifier(required=True)

    example.domain.init(traverse=False)

    with example.domain.domain_context():
        order = example.Order(total=25.0)
        with pytest.raises(IncorrectUsageError):
            order.raise_(OrderShipped(order_id=order.id))


def test_product_keeps_snapshots_and_order_is_event_sourced():
    example = load_example("guides/pathways/event-sourcing/002.py")
    example.domain.init(traverse=False)

    assert example.Product.meta_.is_event_sourced is False
    assert example.Order.meta_.is_event_sourced is True
