"""Fixture: @domain.command injects BaseCommand methods."""

from protean.domain import Domain
from protean.fields import String

domain = Domain(__file__, "TestDomain")


@domain.command
class PlaceOrder:
    order_id = String(required=True)


cmd = PlaceOrder(order_id="123")  # type: ignore[call-arg]
reveal_type(
    cmd.to_dict
)  # E: Revealed type is "def () -> builtins.dict[builtins.str, Any]"
