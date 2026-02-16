"""Fixture: @domain.aggregate injects BaseAggregate methods and auto-id."""

from protean.domain import Domain
from protean.fields import String

domain = Domain(__file__, "TestDomain")


@domain.aggregate
class Customer:
    name = String(required=True)


customer = Customer(name="John")  # type: ignore[call-arg]
reveal_type(customer.id)  # E: Revealed type is "builtins.str"
reveal_type(customer.name)  # E: Revealed type is "builtins.str"
reveal_type(
    customer.to_dict
)  # E: Revealed type is "def () -> builtins.dict[builtins.str, Any]"
customer.raise_  # Should not error — method from BaseAggregate
customer._events  # Should not error — attribute from BaseEntity
