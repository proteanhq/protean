"""Shared domain elements for process manager tests."""

from protean.core.aggregate import BaseAggregate
from protean.core.command import BaseCommand
from protean.core.event import BaseEvent
from protean.core.process_manager import BaseProcessManager
from protean.fields import Float, Identifier, String
from protean.utils.mixins import handle


# --- Aggregates ---


class Order(BaseAggregate):
    customer_id: Identifier()
    total: Float()
    status: String(default="new")

    @classmethod
    def place(cls, customer_id: str, total: float):
        order = cls(customer_id=customer_id, total=total)
        order.raise_(
            OrderPlaced(order_id=order.id, customer_id=customer_id, total=total)
        )
        return order


class Payment(BaseAggregate):
    order_id: Identifier()
    amount: Float()
    status: String(default="pending")

    @classmethod
    def confirm(cls, order_id: str, amount: float):
        payment = cls(order_id=order_id, amount=amount, status="confirmed")
        payment.raise_(
            PaymentConfirmed(payment_id=payment.id, order_id=order_id, amount=amount)
        )
        return payment

    @classmethod
    def fail(cls, order_id: str, reason: str):
        payment = cls(order_id=order_id, amount=0.0, status="failed")
        payment.raise_(
            PaymentFailed(payment_id=payment.id, order_id=order_id, reason=reason)
        )
        return payment


class Shipping(BaseAggregate):
    order_id: Identifier()
    status: String(default="pending")

    @classmethod
    def deliver(cls, order_id: str):
        shipping = cls(order_id=order_id, status="delivered")
        shipping.raise_(ShipmentDelivered(order_id=order_id))
        return shipping


# --- Events ---


class OrderPlaced(BaseEvent):
    order_id: Identifier()
    customer_id: Identifier()
    total: Float()


class PaymentConfirmed(BaseEvent):
    payment_id: Identifier()
    order_id: Identifier()
    amount: Float()


class PaymentFailed(BaseEvent):
    payment_id: Identifier()
    order_id: Identifier()
    reason: String()


class ShipmentDelivered(BaseEvent):
    order_id: Identifier()


# --- Commands ---


class RequestPayment(BaseCommand):
    order_id: Identifier()
    amount: Float()


class CancelOrder(BaseCommand):
    order_id: Identifier()


# --- Process Managers ---


class OrderFulfillmentPM(BaseProcessManager):
    order_id: Identifier()
    payment_id: Identifier()
    status: String(default="new")

    @handle(OrderPlaced, start=True, correlate="order_id")
    def on_order_placed(self, event: OrderPlaced) -> None:
        self.order_id = event.order_id
        self.status = "awaiting_payment"

    @handle(PaymentConfirmed, correlate="order_id")
    def on_payment_confirmed(self, event: PaymentConfirmed) -> None:
        self.payment_id = event.payment_id
        self.status = "awaiting_shipment"

    @handle(PaymentFailed, correlate="order_id", end=True)
    def on_payment_failed(self, event: PaymentFailed) -> None:
        self.status = "cancelled"

    @handle(ShipmentDelivered, correlate="order_id")
    def on_shipment_delivered(self, event: ShipmentDelivered) -> None:
        self.status = "completed"
        self.mark_as_complete()
