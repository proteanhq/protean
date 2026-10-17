from datetime import UTC, datetime

from protean import Domain
from protean.fields import Auto, DateTime, Identifier, String, Text

domain = Domain(name="MyApp")
domain.config["server"]["default_subscription_type"] = "stream"
domain.config["brokers"]["fulfillment_broker"] = {"provider": "inline"}
domain.config["brokers"]["analytics_broker"] = {"provider": "inline"}
domain.config["outbox"]["external_brokers"] = ["fulfillment_broker", "analytics_broker"]


@domain.aggregate
class Order:
    order_id: Auto(identifier=True)
    status: String(default="PLACED")

    def ship(self, tracking_number: str):
        self.status = "SHIPPED"
        self.raise_(
            OrderShipped(
                order_id=self.order_id,
                shipped_at=datetime.now(UTC),
                tracking_number=tracking_number,
            )
        )

    def add_note(self, note: str):
        self.raise_(OrderNoteAdded(order_id=self.order_id, note=note))


# --8<-- [start:events]
@domain.event(part_of=Order, published=True)
class OrderShipped:
    order_id: Identifier(required=True)
    shipped_at: DateTime(required=True)
    tracking_number: String(max_length=50)


@domain.event(part_of=Order)
class OrderNoteAdded:
    """Internal-only event — not published."""

    order_id: Identifier(required=True)
    note: Text()


# --8<-- [end:events]
