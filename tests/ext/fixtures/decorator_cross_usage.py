"""Fixture: cross-type usage — decorator with parens, explicit inheritance."""

from protean.core.aggregate import BaseAggregate
from protean.domain import Domain
from protean.fields import String

domain = Domain(__file__, "TestDomain")


# Test @domain.aggregate() with parentheses
@domain.aggregate()
class Order:
    order_id = String(required=True)


order = Order(order_id="123")  # type: ignore[call-arg]
reveal_type(order.id)  # E: Revealed type is "builtins.str"
reveal_type(
    order.to_dict
)  # E: Revealed type is "def () -> builtins.dict[builtins.str, Any]"


# Test explicit inheritance + decorator — should not double-inject
@domain.aggregate
class Product(BaseAggregate):
    sku = String(required=True)


product = Product()  # type: ignore[call-arg]
reveal_type(
    product.to_dict
)  # E: Revealed type is "def () -> builtins.dict[builtins.str, Any]"
