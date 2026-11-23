"""A generated ``Order`` slice whose authored ``id`` is an ``Identifier`` carries
the id through the aggregate, the raised event and the repository.

Runs inside a project that ``protean new`` generates, after
``tests/scaffold/test_slice_generator.py`` writes the slice into it.
"""

from scaffolded.domain import scaffolded
from scaffolded.order.aggregate import Order
from scaffolded.order.commands import CreateOrder


def test_the_order_is_read_back_by_its_identifier_id() -> None:
    scaffolded.process(CreateOrder(id="order-1", name="a name"))

    assert scaffolded.repository_for(Order).get("order-1").name == "a name"
