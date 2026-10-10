from datetime import UTC, datetime

from protean import Domain, current_domain
from protean.fields import DateTime, Identifier, String

domain = Domain(
    name="MyApp",
    config={
        "server": {"default_subscription_type": "stream"},
        "brokers": {
            "default": {"provider": "inline"},
            "partner_events": {"provider": "inline"},
        },
        "outbox": {"broker": "default", "external_brokers": ["partner_events"]},
    },
)


# --8<-- [start:aggregate]
@domain.aggregate
class Order:
    status: String(max_length=20, default="PLACED")

    def ship(self, tracking_number: str) -> None:
        self.status = "SHIPPED"
        self.raise_(
            OrderShipped(
                order_id=self.id,
                shipped_at=datetime.now(UTC),
                tracking_number=tracking_number,
            )
        )


# --8<-- [end:aggregate]


# --8<-- [start:event]
@domain.event(part_of=Order, published=True)
class OrderShipped:
    order_id: Identifier(required=True)
    shipped_at: DateTime(required=True)
    tracking_number: String(max_length=50)


# --8<-- [end:event]


@domain.event(part_of=Order)
class OrderPacked:
    order_id: Identifier(required=True)


def ship_order(tracking_number: str) -> Order:
    order = Order()
    order.ship(tracking_number)
    current_domain.repository_for(Order).add(order)
    return order


def pack_order() -> Order:
    order = Order()
    order.raise_(OrderPacked(order_id=order.id))
    current_domain.repository_for(Order).add(order)
    return order
