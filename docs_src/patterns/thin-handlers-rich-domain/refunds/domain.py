# --8<-- [start:aggregate]
from datetime import UTC, datetime

from protean import Domain, current_domain, handle
from protean.core.command_handler import BaseCommandHandler
from protean.exceptions import ValidationError
from protean.fields import Auto, DateTime, Float, HasMany, Identifier, Integer, String

domain = Domain(name="ThinHandlersRefunds")


@domain.entity(part_of="Order")
class OrderItem:
    product_id: Identifier(required=True)
    quantity: Integer(min_value=1)
    unit_price: Float()


@domain.command(part_of="Order")
class RequestRefund:
    order_id: Identifier(required=True)
    amount: Float()
    reason: String()


@domain.event(part_of="Order")
class RefundRequested:
    order_id: Identifier(required=True)
    customer_id: Identifier(required=True)
    amount: Float()
    reason: String()


@domain.event(part_of="Order")
class ShipmentInterceptRequested:
    order_id: Identifier(required=True)
    tracking_number: String()


@domain.aggregate
class Order:
    order_id: Auto(identifier=True)
    customer_id: Identifier(required=True)
    items = HasMany(OrderItem)
    status: String(default="draft")
    total: Float(default=0.0)
    partial_refund_amount: Float(default=0.0)
    refund_amount: Float()
    refund_reason: String()
    refund_requested_at: DateTime()
    delivered_at: DateTime()
    tracking_number: String()

    REFUND_WINDOW_DAYS = 30

    def request_refund(self, amount: float | None = None, reason: str = "") -> None:
        """Request a refund for this order."""
        self._validate_refund_eligibility()

        refund_amount = self._calculate_refund_amount(amount)
        needs_intercept = self._needs_shipment_intercept()

        self.status = "refund_requested"
        self.refund_amount = refund_amount
        self.refund_requested_at = datetime.now(UTC)
        self.refund_reason = reason

        self.raise_(
            RefundRequested(
                order_id=self.order_id,
                customer_id=self.customer_id,
                amount=refund_amount,
                reason=reason,
            )
        )

        if needs_intercept:
            self.raise_(
                ShipmentInterceptRequested(
                    order_id=self.order_id,
                    tracking_number=self.tracking_number,
                )
            )

    def _validate_refund_eligibility(self) -> None:
        """Check if this order can be refunded."""
        if self.status not in ("shipped", "delivered"):
            raise ValidationError(
                {"status": ["Only shipped or delivered orders can be refunded"]}
            )

        if self.delivered_at:
            delivered_at = self.delivered_at
            # A database without time zones, such as SQLite, returns a naive value
            if delivered_at.tzinfo is None:
                delivered_at = delivered_at.replace(tzinfo=UTC)
            days_since = (datetime.now(UTC) - delivered_at).days
            if days_since > self.REFUND_WINDOW_DAYS:
                raise ValidationError(
                    {
                        "timing": [
                            f"Refund window has expired ({self.REFUND_WINDOW_DAYS} days)"
                        ]
                    }
                )

    def _calculate_refund_amount(self, requested_amount: float | None = None) -> float:
        """Calculate the actual refund amount."""
        max_refundable = self.total - self.partial_refund_amount
        if max_refundable <= 0:
            raise ValidationError({"amount": ["Nothing is left to refund"]})

        if requested_amount is None:
            return max_refundable

        if requested_amount <= 0:
            raise ValidationError({"amount": ["Refund amount must be positive"]})

        return min(requested_amount, max_refundable)

    def _needs_shipment_intercept(self) -> bool:
        """Check if we need to intercept the shipment."""
        return self.status == "shipped" and not self.delivered_at


# --8<-- [end:aggregate]


# --8<-- [start:handler]
@domain.command_handler(part_of=Order)
class OrderCommandHandler(BaseCommandHandler):
    @handle(RequestRefund)
    def request_refund(self, command: RequestRefund):
        repo = current_domain.repository_for(Order)
        order = repo.get(command.order_id)
        order.request_refund(
            amount=command.amount,
            reason=command.reason,
        )
        repo.add(order)


# --8<-- [end:handler]
