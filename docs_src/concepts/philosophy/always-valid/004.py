from protean import Domain, invariant
from protean.exceptions import ValidationError
from protean.fields import (
    DateTime,
    Float,
    HasMany,
    Identifier,
    Integer,
    String,
    ValueObject,
)

domain = Domain(name="AlwaysValidGuards")
domain.config["command_processing"] = "sync"


@domain.value_object
class Money:
    amount: Float(required=True)
    currency: String(required=True, max_length=3)


@domain.aggregate
class Order:
    customer_id: Identifier(required=True)
    status: String(max_length=20, default="draft")
    total = ValueObject(Money)
    items = HasMany("OrderItem")
    placed_at: DateTime()
    cancellation_reason: String(max_length=500)

    @invariant.post
    def must_have_items_when_placed(self):
        if self.status != "draft" and not self.items:
            raise ValidationError({"items": ["Order must have at least one item"]})

    def cancel(self, reason):
        self.status = "cancelled"
        self.cancellation_reason = reason


@domain.entity(part_of=Order)
class OrderItem:
    product_name: String(required=True, max_length=200)
    quantity: Integer(required=True, min_value=1)
    unit_price: Float(required=True, min_value=0.01)


# --8<-- [start:handler]
from datetime import UTC, datetime

from protean import handle
from protean.fields import Identifier, String
from protean.utils.globals import current_domain


@domain.command(part_of=Order)
class CancelOrder:
    order_id: Identifier(required=True)
    cancelled_by: Identifier(required=True)
    cancelled_by_role: String(required=True)
    reason: String(max_length=500)


@domain.command_handler(part_of=Order)
class OrderCommandHandler:
    @handle(CancelOrder)
    def cancel_order(self, command: CancelOrder):
        repo = current_domain.repository_for(Order)
        order = repo.get(command.order_id)

        # Guard: authorization
        if (
            command.cancelled_by_role != "admin"
            and command.cancelled_by != order.customer_id
        ):
            raise ValidationError(
                {"authorization": ["Only the customer or an admin can cancel"]}
            )

        # Guard: time-based business rule
        if order.placed_at:
            hours = (datetime.now(UTC) - order.placed_at).total_seconds() / 3600
            if hours > 24:
                raise ValidationError(
                    {"timing": ["Orders cannot be cancelled after 24 hours"]}
                )

        # Delegate to aggregate (which has its own Layer 3 invariants)
        order.cancel(command.reason)
        repo.add(order)


# --8<-- [end:handler]
