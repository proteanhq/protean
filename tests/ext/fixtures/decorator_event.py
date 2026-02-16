"""Fixture: @domain.event injects BaseEvent methods."""

from protean.domain import Domain
from protean.fields import String

domain = Domain(__file__, "TestDomain")


@domain.event
class OrderPlaced:
    order_id = String(required=True)


evt = OrderPlaced(order_id="123")  # type: ignore[call-arg]
reveal_type(
    evt.to_dict
)  # E: Revealed type is "def () -> builtins.dict[builtins.str, Any]"
