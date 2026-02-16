"""Fixture: @domain.value_object injects BaseValueObject methods."""

from protean.domain import Domain
from protean.fields import Integer

domain = Domain(__file__, "TestDomain")


@domain.value_object
class Money:
    amount = Integer(required=True)


money = Money(amount=100)  # type: ignore[call-arg]
reveal_type(
    money.to_dict
)  # E: Revealed type is "def () -> builtins.dict[builtins.str, Any]"
