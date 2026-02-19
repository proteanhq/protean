from protean import Domain, handle
from protean.fields import Float, Identifier, String

domain = Domain(__file__, "ecommerce")


@domain.event(part_of="Order")
class OrderPlaced:
    order_id: Identifier(required=True)
    customer_id: Identifier(required=True)
    total: Float(required=True)


@domain.event(part_of="Payment")
class PaymentConfirmed:
    payment_id: Identifier(required=True)
    order_id: Identifier(required=True)
    amount: Float(required=True)


@domain.event(part_of="Payment")
class PaymentFailed:
    payment_id: Identifier(required=True)
    order_id: Identifier(required=True)
    reason: String(required=True)


@domain.event(part_of="Shipping")
class ShipmentDelivered:
    order_id: Identifier(required=True)


@domain.aggregate
class Order:
    customer_id: Identifier(required=True)
    total: Float(required=True)
    status: String(default="new")


@domain.aggregate
class Payment:
    order_id: Identifier(required=True)
    amount: Float(required=True)


@domain.aggregate
class Shipping:
    order_id: Identifier(required=True)


@domain.process_manager(
    stream_categories=["ecommerce::order", "ecommerce::payment", "ecommerce::shipping"]
)
class OrderFulfillmentPM:
    order_id: Identifier()
    payment_id: Identifier()
    status: String(default="new")

    @handle(OrderPlaced, start=True, correlate="order_id")  # (1) (2)
    def on_order_placed(self, event: OrderPlaced) -> None:
        self.order_id = event.order_id
        self.status = "awaiting_payment"

    @handle(PaymentConfirmed, correlate="order_id")
    def on_payment_confirmed(self, event: PaymentConfirmed) -> None:
        self.payment_id = event.payment_id
        self.status = "awaiting_shipment"

    @handle(PaymentFailed, correlate="order_id", end=True)  # (3)
    def on_payment_failed(self, event: PaymentFailed) -> None:
        self.status = "cancelled"

    @handle(ShipmentDelivered, correlate="order_id")
    def on_shipment_delivered(self, event: ShipmentDelivered) -> None:
        self.status = "completed"
        self.mark_as_complete()  # (4)
