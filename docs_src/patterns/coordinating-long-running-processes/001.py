from protean import Domain

domain = Domain(name="ecommerce")

# --8<-- [start:aggregates]
from protean.fields import Identifier


# Cut down to one field each. Their own state and rules are not part of
# this pattern.
@domain.aggregate
class Order:
    customer_id: Identifier()


@domain.aggregate
class Payment:
    order_id: Identifier()


@domain.aggregate
class Inventory:
    order_id: Identifier()


@domain.aggregate
class Shipping:
    order_id: Identifier()


# --8<-- [end:aggregates]

# --8<-- [start:messages]
from protean.fields import Float, Identifier, String

# --- Events the PM reacts to ---


@domain.event(part_of="Order")
class OrderPlaced:
    order_id: Identifier(required=True)
    customer_id: Identifier(required=True)
    total: Float()


@domain.event(part_of="Payment")
class PaymentConfirmed:
    payment_id: Identifier(required=True)
    order_id: Identifier(required=True)
    amount: Float()


@domain.event(part_of="Payment")
class PaymentFailed:
    payment_id: Identifier(required=True)
    order_id: Identifier(required=True)
    reason: String()


@domain.event(part_of="Inventory")
class InventoryReserved:
    order_id: Identifier(required=True)
    product_id: Identifier(required=True)


@domain.event(part_of="Inventory")
class InventoryReservationFailed:
    order_id: Identifier(required=True)
    reason: String()


@domain.event(part_of="Shipping")
class ShipmentCreated:
    shipment_id: Identifier(required=True)
    order_id: Identifier(required=True)


@domain.event(part_of="Shipping")
class ShipmentDelivered:
    shipment_id: Identifier(required=True)
    order_id: Identifier(required=True)


@domain.event(part_of="Shipping")
class ShipmentRejected:
    shipment_id: Identifier(required=True)
    order_id: Identifier(required=True)
    reason: String()


# --- Timeout event (published by an external scheduled job) ---


@domain.event(part_of="Order")
class OrderFulfillmentTimedOut:
    order_id: Identifier(required=True)
    stalled_status: String()


# --- Commands the PM issues ---


@domain.command(part_of="Inventory")
class ReserveInventory:
    order_id: Identifier(required=True)


@domain.command(part_of="Inventory")
class ReleaseInventory:
    order_id: Identifier(required=True)


@domain.command(part_of="Payment")
class RequestPayment:
    order_id: Identifier(required=True)
    amount: Float()


@domain.command(part_of="Payment")
class RefundPayment:
    order_id: Identifier(required=True)
    payment_id: Identifier(required=True)


@domain.command(part_of="Shipping")
class CreateShipment:
    order_id: Identifier(required=True)


@domain.command(part_of="Shipping")
class CancelShipment:
    order_id: Identifier(required=True)
    shipment_id: Identifier(required=True)


@domain.command(part_of="Order")
class CancelOrder:
    order_id: Identifier(required=True)
    reason: String()


# --8<-- [end:messages]


# --8<-- [start:process_manager]
from protean import current_domain, handle
from protean.fields import Identifier, String


@domain.process_manager(
    stream_categories=[
        "ecommerce::order",
        "ecommerce::payment",
        "ecommerce::inventory",
        "ecommerce::shipping",
    ]
)
class OrderFulfillmentPM:
    order_id: Identifier()
    payment_id: Identifier()
    shipment_id: Identifier()
    status: String(default="new")

    # -----------------------------------------------------------
    # Step 1: Order placed -- start the process
    # -----------------------------------------------------------
    @handle(OrderPlaced, start=True, correlate="order_id")
    def on_order_placed(self, event: OrderPlaced) -> None:
        if self.status != "new":
            return  # Idempotent: already started

        self.order_id = event.order_id
        self.status = "awaiting_inventory"
        current_domain.process(ReserveInventory(order_id=event.order_id))

    # -----------------------------------------------------------
    # Step 2a: Inventory reserved -- request payment
    # -----------------------------------------------------------
    @handle(InventoryReserved, correlate="order_id")
    def on_inventory_reserved(self, event: InventoryReserved) -> None:
        if self.status != "awaiting_inventory":
            return  # Idempotent or out-of-order

        self.status = "awaiting_payment"
        current_domain.process(
            RequestPayment(
                order_id=self.order_id,
                amount=0.0,  # Amount resolved by Payment aggregate
            )
        )

    # -----------------------------------------------------------
    # Step 2b: Inventory reservation failed -- cancel order
    # -----------------------------------------------------------
    @handle(InventoryReservationFailed, correlate="order_id")
    def on_inventory_failed(self, event: InventoryReservationFailed) -> None:
        if self.status not in ("awaiting_inventory", "new"):
            return

        self.status = "cancelled"
        current_domain.process(
            CancelOrder(
                order_id=self.order_id,
                reason=f"Inventory unavailable: {event.reason}",
            )
        )
        self.mark_as_complete()

    # -----------------------------------------------------------
    # Step 3a: Payment confirmed -- create shipment
    # -----------------------------------------------------------
    @handle(PaymentConfirmed, correlate="order_id")
    def on_payment_confirmed(self, event: PaymentConfirmed) -> None:
        if self.status != "awaiting_payment":
            return  # Idempotent: already past payment step

        self.payment_id = event.payment_id
        self.status = "awaiting_shipment"
        current_domain.process(CreateShipment(order_id=self.order_id))

    # -----------------------------------------------------------
    # Step 3b: Payment failed -- release inventory, cancel order
    # -----------------------------------------------------------
    @handle(PaymentFailed, correlate="order_id")
    def on_payment_failed(self, event: PaymentFailed) -> None:
        if self.status != "awaiting_payment":
            return

        self.status = "cancelled"
        current_domain.process(ReleaseInventory(order_id=self.order_id))
        current_domain.process(
            CancelOrder(
                order_id=self.order_id,
                reason=f"Payment failed: {event.reason}",
            )
        )
        self.mark_as_complete()

    # -----------------------------------------------------------
    # Step 4a: Shipment created -- record shipment ID
    # -----------------------------------------------------------
    @handle(ShipmentCreated, correlate="order_id")
    def on_shipment_created(self, event: ShipmentCreated) -> None:
        if self.status != "awaiting_shipment":
            return

        self.shipment_id = event.shipment_id
        self.status = "awaiting_delivery"

    # -----------------------------------------------------------
    # Step 4b: Shipment rejected -- refund payment, release
    #          inventory, cancel order
    # -----------------------------------------------------------
    @handle(ShipmentRejected, correlate="order_id")
    def on_shipment_rejected(self, event: ShipmentRejected) -> None:
        if self.status not in ("awaiting_shipment", "awaiting_delivery"):
            return

        self.status = "cancelled"

        # Compensate: refund the payment
        current_domain.process(
            RefundPayment(
                order_id=self.order_id,
                payment_id=self.payment_id,
            )
        )
        # Compensate: release inventory
        current_domain.process(ReleaseInventory(order_id=self.order_id))
        # Compensate: cancel the order
        current_domain.process(
            CancelOrder(
                order_id=self.order_id,
                reason=f"Shipment rejected: {event.reason}",
            )
        )
        self.mark_as_complete()

    # -----------------------------------------------------------
    # Step 5: Shipment delivered -- process complete
    # -----------------------------------------------------------
    @handle(ShipmentDelivered, correlate="order_id")
    def on_shipment_delivered(self, event: ShipmentDelivered) -> None:
        if self.status != "awaiting_delivery":
            return

        self.status = "completed"
        self.mark_as_complete()

    # -----------------------------------------------------------
    # Timeout: external timer detected a stalled process
    # -----------------------------------------------------------
    @handle(OrderFulfillmentTimedOut, correlate="order_id")
    def on_timeout(self, event: OrderFulfillmentTimedOut) -> None:
        if self.status in ("completed", "cancelled"):
            return  # Already terminal

        # Compensate based on how far the process progressed
        if self.shipment_id:
            current_domain.process(
                CancelShipment(order_id=self.order_id, shipment_id=self.shipment_id)
            )
        if self.payment_id:
            current_domain.process(
                RefundPayment(order_id=self.order_id, payment_id=self.payment_id)
            )
        if self.status != "new":
            current_domain.process(ReleaseInventory(order_id=self.order_id))

        self.status = "cancelled"
        self.mark_as_complete()
        current_domain.process(
            CancelOrder(
                order_id=self.order_id,
                reason=f"Timed out in '{event.stalled_status}' status",
            )
        )


# --8<-- [end:process_manager]
