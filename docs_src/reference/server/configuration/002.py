from protean import Domain, handle
from protean.fields import Float, Identifier, String

domain = Domain(name="Shop")


# --8<-- [start:model]
@domain.aggregate
class Order:
    total: Float()


@domain.event(part_of=Order)
class OrderCreated:
    order_id: Identifier(required=True)


@domain.event(part_of=Order)
class OrderShipped:
    order_id: Identifier(required=True)


@domain.aggregate
class Notification:
    message: String()


@domain.aggregate
class Inventory:
    sku: String()


@domain.projection
class OrderSummary:
    order_id: Identifier(identifier=True)
    total: Float()


# --8<-- [end:model]


# --8<-- [start:decorator]
@domain.event_handler(
    part_of=Order,
    subscription_type="stream",
    subscription_profile="production",
    subscription_config={
        "messages_per_tick": 50,
        "enable_dlq": True,
    },
)
class OrderEventHandler:
    @handle(OrderCreated)
    def handle_order_created(self, event): ...


# --8<-- [end:decorator]
