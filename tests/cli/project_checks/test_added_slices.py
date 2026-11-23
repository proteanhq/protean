"""The ``Order`` and ``OrderItem`` slices that ``protean add`` applies register
under traversal and process their create command.

Runs inside a project that ``protean new`` generates, under the project's own
``conftest.py``, which initialises the domain with traversal on.
"""

import pytest
from scaffolded.domain import scaffolded as domain


@pytest.mark.parametrize("name", ["Order", "OrderItem"])
def test_the_slice_registers_under_traversal(name: str) -> None:
    expected = {
        name,
        f"Create{name}",
        f"{name}Created",
        f"{name}CommandHandler",
        f"{name}Summary",
        f"{name}Projector",
    }

    registered = set(domain.registry._elements_by_name)

    assert expected <= registered, f"missing: {sorted(expected - registered)}"


# The slice modules are imported inside the tests, after the domain has
# initialised. An import at module level would run during collection and
# register the elements itself, so the test above would no longer show that
# traversal finds them.


def test_create_order_persists_an_order() -> None:
    from scaffolded.order.aggregate import Order
    from scaffolded.order.commands import CreateOrder

    order_id = domain.process(CreateOrder(name="Widget"))

    assert domain.repository_for(Order).get(order_id).name == "Widget"


def test_create_order_item_persists_an_order_item() -> None:
    from scaffolded.order_item.aggregate import OrderItem
    from scaffolded.order_item.commands import CreateOrderItem

    item_id = domain.process(CreateOrderItem(name="Widget"))

    assert domain.repository_for(OrderItem).get(item_id).name == "Widget"
