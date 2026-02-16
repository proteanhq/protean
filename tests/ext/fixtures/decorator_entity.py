"""Fixture: @domain.entity injects BaseEntity methods and auto-id."""

from protean.domain import Domain
from protean.fields import String

domain = Domain(__file__, "TestDomain")


@domain.entity
class Address:
    street = String(required=True)


addr = Address(street="Main St")  # type: ignore[call-arg]
reveal_type(addr.id)  # E: Revealed type is "builtins.str"
reveal_type(
    addr.to_dict
)  # E: Revealed type is "def () -> builtins.dict[builtins.str, Any]"
addr._events  # Should not error — attribute from BaseEntity
