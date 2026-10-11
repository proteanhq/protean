from protean import Domain, current_domain, handle
from protean.fields import Float, Identifier, String

domain = Domain(name="ecommerce")


@domain.event(part_of="Order")
class OrderPlaced:
    order_id: Identifier(required=True)
    customer_id: Identifier(required=True)
    total: Float(required=True)


@domain.command(part_of="Order")
class ReserveInventory:
    order_id: Identifier(required=True)


@domain.aggregate
class Order:
    customer_id: Identifier(required=True)
    total: Float(required=True)


# --8<-- [start:external_events]
from protean.core.event import BaseEvent
from protean.fields import Float, Identifier


# Define external event classes in YOUR domain (no imports from other packages)
class PaymentReceived(BaseEvent):
    payment_id = Identifier(required=True)
    order_id = Identifier(required=True)
    amount = Float()


class InventoryReserved(BaseEvent):
    order_id = Identifier(required=True)
    product_id = Identifier(required=True)


class InventoryUnavailable(BaseEvent):
    order_id = Identifier(required=True)
    product_id = Identifier(required=True)


# Register them with the type strings used by the publishing domains
domain.register_external_event(PaymentReceived, "Billing.PaymentReceived.v1")
domain.register_external_event(InventoryReserved, "Inventory.InventoryReserved.v1")
domain.register_external_event(
    InventoryUnavailable, "Inventory.InventoryUnavailable.v1"
)
# --8<-- [end:external_events]


# --8<-- [start:process_manager]
@domain.process_manager(
    stream_categories=[
        "ecommerce::order",  # Own domain
        "billing::payment",  # External domain
        "inventory::inventory_item",  # External domain
    ]
)
class OrderFulfillmentPM:
    order_id = Identifier()
    status = String(default="new")

    @handle(OrderPlaced, start=True, correlate="order_id")
    def on_order_placed(self, event: OrderPlaced) -> None:
        self.order_id = event.order_id
        self.status = "awaiting_payment"

    @handle(PaymentReceived, correlate="order_id")
    def on_payment_received(self, event: PaymentReceived) -> None:
        if self.status != "awaiting_payment":
            return
        self.status = "awaiting_inventory"
        current_domain.process(ReserveInventory(order_id=self.order_id))

    @handle(InventoryReserved, correlate="order_id")
    def on_inventory_reserved(self, event: InventoryReserved) -> None:
        if self.status != "awaiting_inventory":
            return
        self.status = "completed"
        self.mark_as_complete()

    @handle(InventoryUnavailable, correlate="order_id", end=True)
    def on_inventory_unavailable(self, event: InventoryUnavailable) -> None:
        self.status = "inventory_unavailable"


# --8<-- [end:process_manager]
