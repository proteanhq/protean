from protean import Domain, current_domain, handle
from protean.fields import Float, Identifier, String

domain = Domain(__file__, "ecommerce")


@domain.command(part_of="Payment")
class RequestPayment:
    order_id: Identifier(required=True)
    amount: Float(required=True)


@domain.command(part_of="Order")
class CancelOrder:
    order_id: Identifier(required=True)


@domain.event(part_of="Order")
class OrderPlaced:
    order_id: Identifier(required=True)
    customer_id: Identifier(required=True)
    total: Float(required=True)


@domain.event(part_of="Payment")
class PaymentFailed:
    payment_id: Identifier(required=True)
    order_id: Identifier(required=True)
    reason: String(required=True)


@domain.aggregate
class Order:
    customer_id: Identifier(required=True)
    total: Float(required=True)


@domain.aggregate
class Payment:
    order_id: Identifier(required=True)
    amount: Float(required=True)


@domain.process_manager(stream_categories=["ecommerce::order", "ecommerce::payment"])
class OrderPaymentPM:
    order_id: Identifier()
    status: String(default="new")

    @handle(OrderPlaced, start=True, correlate="order_id")
    def on_order_placed(self, event: OrderPlaced) -> None:
        self.order_id = event.order_id
        self.status = "awaiting_payment"
        current_domain.process(  # (1)
            RequestPayment(order_id=event.order_id, amount=event.total)
        )

    @handle(PaymentFailed, correlate="order_id", end=True)
    def on_payment_failed(self, event: PaymentFailed) -> None:
        self.status = "cancelled"
        current_domain.process(  # (2)
            CancelOrder(order_id=self.order_id)
        )
