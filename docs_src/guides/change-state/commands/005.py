from protean import Domain, handle
from protean.fields import Identifier, List, String

domain = Domain(name="Sales")


@domain.aggregate
class Order:
    items: List(content_type=String)


@domain.command(part_of=Order)
class PlaceOrder:
    order_id: Identifier(identifier=True)


# --8<-- [start:handler_timeout]
# Per-handler default (seconds or a timedelta)
@domain.command_handler(part_of=Order, timeout=30)
class OrderCommandHandler:
    @handle(PlaceOrder)
    def place(self, command: PlaceOrder):
        # A PlaceOrder sent with no deadline gets one 30 seconds out
        return command._metadata.headers.deadline


# --8<-- [end:handler_timeout]
