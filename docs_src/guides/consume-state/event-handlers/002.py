from protean import Domain, current_domain, handle
from protean.fields import Dict, Identifier, Integer, String

domain = Domain(name="Orders")
domain.config["event_processing"] = "sync"


@domain.event(part_of="Order")
class OrderPlaced:
    order_id: Identifier(required=True)
    quantity: Integer(required=True)


@domain.event(part_of="Order")
class OrderShipped:
    order_id: Identifier(required=True)


@domain.aggregate
class Order:
    quantity: Integer(required=True)

    def place(self):
        self.raise_(OrderPlaced(order_id=self.id, quantity=self.quantity))

    def ship(self):
        self.raise_(OrderShipped(order_id=self.id))


# --8<-- [start:audit]
@domain.aggregate
class AuditEntry:
    event_type: String(required=True)
    payload: Dict()

    @classmethod
    def from_event(cls, event):
        return cls(event_type=event.__class__.__name__, payload=event.payload)


@domain.event_handler(part_of=Order)
class OrderAudit:
    @handle("$any")
    def record(self, event):
        current_domain.repository_for(AuditEntry).add(AuditEntry.from_event(event))


# --8<-- [end:audit]


# --8<-- [start:source-stream]
@domain.event_handler(part_of=Order, source_stream="manage_order")
class EmailNotifications:
    @handle(OrderShipped)
    def send_shipping_email(self, event: OrderShipped):
        # Only invoked when OrderShipped was triggered by a command
        # in the manage_order stream, not by a bulk import or replay.
        ...


# --8<-- [end:source-stream]


# --8<-- [start:subscription-config]
@domain.event_handler(
    part_of=Order,
    subscription_profile="production",
    subscription_config={
        "messages_per_tick": 100,
        "enable_dlq": True,
    },
)
class OrderEventHandler:
    @handle(OrderPlaced)
    def send_confirmation(self, event): ...


# --8<-- [end:subscription-config]


# --8<-- [start:dlq]
@domain.event_handler(
    part_of=Order,
    subscription_type="stream",
    subscription_config={
        "max_retries": 5,
        "enable_dlq": True,
    },
)
class CriticalOrderHandler:
    @handle(OrderPlaced)
    def process_order(self, event: OrderPlaced):
        # If this fails 5 times, the message moves to the DLQ
        ...


# --8<-- [end:dlq]


# --8<-- [start:transient-retries]
@domain.event_handler(part_of=Order, retries=3, backoff="exponential")
class InventorySync:
    @handle(OrderPlaced)
    def reserve_stock(self, event: OrderPlaced):
        # A ConnectionError here is retried up to 3 times with exponential
        # backoff before the failure surfaces to the subscription.
        ...


# --8<-- [end:transient-retries]
