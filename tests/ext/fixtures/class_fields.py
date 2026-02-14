"""Fixture: fields in a class resolve to correct types via attribute access."""

from protean.core.aggregate import BaseAggregate
from protean.fields import String, Integer, Float, Boolean


class Order(BaseAggregate):
    customer_name = String(max_length=100, required=True)
    quantity = Integer(min_value=1)
    price = Float(min_value=0)
    is_active = Boolean(default=True)


order = Order()  # type: ignore[call-arg]
reveal_type(order.customer_name)  # E: Revealed type is "builtins.str"
reveal_type(order.quantity)  # E: Revealed type is "builtins.int | None"
reveal_type(order.price)  # E: Revealed type is "builtins.float | None"
reveal_type(order.is_active)  # E: Revealed type is "builtins.bool"
