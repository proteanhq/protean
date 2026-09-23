"""
One oversized Order aggregate, before the split.

Order has accreted a second concern. The order concern (items, discounts, gift
wraps) and the fulfilment concern (packages, tracking events, delivery
attempts) both live inside the one aggregate. That puts more child entities in a
single cluster than the default `aggregate_size_limit` allows, so `check`
reports AGGREGATE_TOO_LARGE for Order.

The fix is in split_order_after.py: pull the fulfilment concern out into its own
Shipment aggregate, linked to Order by identity and driven by a domain event.

Usage:
    from split_order_before import PlaceOrder, domain

    domain.init(traverse=False)
    # `check` reports AGGREGATE_TOO_LARGE for Order: too many child entities.
"""

from protean import Domain, handle, invariant
from protean.exceptions import ValidationError
from protean.fields import DateTime, Float, HasMany, Identifier, Integer, String

domain = Domain(__file__, "ecommerce")


@domain.command(part_of="Order")
class PlaceOrder:
    """Place an order. The caller chooses the order id."""

    order_id: Identifier(required=True)
    customer_id: Identifier(required=True)
    total: Float(required=True)


@domain.aggregate
class Order:
    """An order that also carries its own fulfilment state.

    The order concern and the fulfilment concern are both here. That is the
    smell: separate lifecycles and separate consistency boundaries in one aggregate.
    """

    customer_id: Identifier(required=True)
    total: Float(default=0.0)
    status: String(default="draft")

    # Order concern.
    items = HasMany("OrderItem")
    discounts = HasMany("Discount")
    gift_wraps = HasMany("GiftWrap")

    # Fulfilment concern. This is the seam the split follows.
    packages = HasMany("Package")
    tracking_events = HasMany("TrackingEvent")
    delivery_attempts = HasMany("DeliveryAttempt")

    @classmethod
    def place(cls, order_id: str, customer_id: str, total: float) -> "Order":
        """Place an order."""
        return cls(id=order_id, customer_id=customer_id, total=total, status="placed")

    @invariant.post
    def total_must_not_be_negative(self) -> None:
        """An order's total cannot be negative."""
        if self.total < 0:
            raise ValidationError({"total": ["Order total cannot be negative"]})


# --- Order concern entities ---


@domain.entity(part_of="Order")
class OrderItem:
    """A line on the order."""

    product_id: Identifier(required=True)
    quantity: Integer(required=True, min_value=1)
    unit_price: Float(required=True, min_value=0.0)


@domain.entity(part_of="Order")
class Discount:
    """A discount applied to the order."""

    code: String(required=True, max_length=50)
    amount: Float(required=True, min_value=0.0)


@domain.entity(part_of="Order")
class GiftWrap:
    """A gift-wrap request on the order."""

    style: String(required=True, max_length=50)


# --- Fulfilment concern entities (these move out in the after) ---


@domain.entity(part_of="Order")
class Package:
    """A physical package prepared for the order."""

    weight_kg: Float(required=True, min_value=0.0)


@domain.entity(part_of="Order")
class TrackingEvent:
    """A carrier tracking update for the order."""

    status: String(required=True, max_length=50)
    note: String(max_length=200)


@domain.entity(part_of="Order")
class DeliveryAttempt:
    """One attempt to deliver the order."""

    attempted_at: DateTime()
    outcome: String(required=True, max_length=50)


@domain.command_handler(part_of=Order)
class OrderCommandHandler:
    """The write path for Order."""

    @handle(PlaceOrder)
    def place_order(self, command: PlaceOrder) -> None:
        order = Order.place(command.order_id, command.customer_id, command.total)
        domain.repository_for(Order).add(order)
