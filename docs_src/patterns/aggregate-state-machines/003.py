from enum import Enum

from protean import Domain

domain = Domain(name="OrderStateMachineInvariants")


class OrderStatus(Enum):
    DRAFT = "draft"
    PLACED = "placed"
    PAID = "paid"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"
    REFUNDED = "refunded"


# --8<-- [start:invariants]
from typing import ClassVar

from protean import invariant
from protean.exceptions import ValidationError
from protean.fields import Auto, DateTime, Identifier, String


@domain.aggregate
class Order:
    order_id = Auto(identifier=True)
    customer_id = Identifier(required=True)
    status = String(choices=OrderStatus, default=OrderStatus.DRAFT.value)
    tracking_number = String()
    shipped_at = DateTime()

    TERMINAL_STATES: ClassVar[set[str]] = {
        OrderStatus.DELIVERED.value,
        OrderStatus.CANCELLED.value,
        OrderStatus.REFUNDED.value,
    }

    @invariant.pre
    def cannot_modify_terminal_order(self):
        """Safety net: no mutations allowed on orders in terminal states."""
        if self.status in self.TERMINAL_STATES:
            raise ValidationError(
                {"status": [f"Order in '{self.status}' status cannot be modified"]}
            )

    @invariant.post
    def shipped_order_must_have_tracking(self):
        """A shipped order must always have a tracking number."""
        if self.status == OrderStatus.SHIPPED.value and not self.tracking_number:
            raise ValidationError(
                {"tracking_number": ["Shipped orders must have a tracking number"]}
            )

    @invariant.post
    def shipped_order_must_have_timestamp(self):
        """A shipped order must always have a shipped_at timestamp."""
        if self.status == OrderStatus.SHIPPED.value and not self.shipped_at:
            raise ValidationError(
                {"shipped_at": ["Shipped orders must have a shipped_at timestamp"]}
            )


# --8<-- [end:invariants]
