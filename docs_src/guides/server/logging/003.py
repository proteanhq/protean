# --8<-- [start:model]
from protean import Domain
from protean.fields import Float, Identifier, String

domain = Domain(name="Orders")


@domain.aggregate
class Order:
    customer_id: Identifier(required=True)
    total: Float(required=True)


@domain.command(part_of=Order)
class PlaceOrder:
    customer_id: Identifier(required=True)
    total: Float(required=True)
    user_tier: String(default="standard")
    coupon_code: String()


# --8<-- [end:model]


# --8<-- [start:handler]
from protean import handle
from protean.utils.logging import bind_event_context


@domain.command_handler(part_of=Order)
class OrderCommandHandler:
    @handle(PlaceOrder)
    def place(self, command: PlaceOrder) -> None:
        bind_event_context(
            user_tier=command.user_tier,
            order_total=float(command.total),
            coupon_applied=command.coupon_code is not None,
        )
        # ... handler logic ...


# --8<-- [end:handler]
