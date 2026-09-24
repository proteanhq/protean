"""
Domain unit testing scaffold: Order aggregate with entities, value objects, and invariants.

This example demonstrates:
- Aggregate with factory method, state transitions, and event raising
- Entity management (add/remove line items)
- Value object with custom operations (Money.add())
- User-defined invariants (@invariant.post)
- Business rules that reject invalid operations

Domain: An e-commerce Order that contains LineItems with Money prices.
Orders can be placed (which raises OrderPlaced) and cancelled (which raises
OrderCancelled), with business rules guarding both transitions.
"""

from protean import Domain, invariant
from protean.exceptions import ValidationError
from protean.fields import (
    Float,
    HasMany,
    Identifier,
    Integer,
    String,
    ValueObject,
)

domain = Domain(__name__)
domain.config["event_processing"] = "sync"


# --- Value Object ---


@domain.value_object
class Money:
    """Money value object with custom add operation.

    Encapsulates amount + currency. The add() method is user-defined
    business logic (not a framework feature) and should be tested.
    """

    amount: Float(required=True)
    currency: String(max_length=3, default="USD")

    def add(self, other: "Money") -> "Money":
        """Add two Money values. Requires same currency."""
        if self.currency != other.currency:
            raise ValueError(f"Cannot add {self.currency} and {other.currency}")
        return Money(amount=self.amount + other.amount, currency=self.currency)


# --- Events ---


@domain.event(part_of="Order")
class OrderPlaced:
    """Raised when an order is placed."""

    order_id: Identifier(required=True)
    customer_id: String(required=True)
    item_count: Integer(required=True)
    total_amount: Float(required=True)


@domain.event(part_of="Order")
class OrderCancelled:
    """Raised when an order is cancelled."""

    order_id: Identifier(required=True)
    reason: String(required=True)


# --- Entity ---


@domain.entity(part_of="Order")
class LineItem:
    """Line item entity belonging to an Order."""

    product_id: String(required=True, max_length=50)
    quantity: Integer(required=True, min_value=1)
    unit_price: ValueObject(Money, required=True)

    @property
    def subtotal(self) -> float:
        """Calculate line item subtotal."""
        return self.quantity * self.unit_price.amount


# --- Aggregate ---


@domain.aggregate
class Order:
    """Order aggregate with business rules, invariants, and event raising.

    `total` folds the item prices with `Money.add()`, so an order holding two
    currencies cannot produce one.
    """

    customer_id: String(required=True, max_length=50)
    status: String(default="draft")
    line_items = HasMany(LineItem)

    # --- Invariants (user-defined business rules) ---

    @invariant.post
    def must_have_items_when_placed(self):
        """Placed orders must have at least one item."""
        if self.status == "placed" and not self.line_items:
            raise ValidationError(
                {"_entity": ["Order must have at least one item to be placed"]}
            )

    # --- Factory method ---

    @classmethod
    def create(cls, customer_id, items=None):
        """Factory: create a new draft order.

        `items` takes dicts in `add_item`'s shape, or `LineItem`s already
        built. Dicts go through `add_item`, so a caller who passes a plain
        price gets the same `Money` wrapping a direct call gives them.
        """
        order = cls(customer_id=customer_id)
        for item in items or []:
            if isinstance(item, dict):
                order.add_item(**item)
            else:
                order.add_line_items(item)
        return order

    # --- Business methods ---

    def add_item(self, product_id, quantity, unit_price):
        """Add a line item to the order.

        Takes the price as a plain number and wraps it in `Money`. There is no
        currency argument: `total` sums the amounts, and `Money.add()` refuses
        to add across currencies, so an order that mixed them would contradict
        its own value object.
        """
        item = LineItem(
            product_id=product_id,
            quantity=quantity,
            unit_price=Money(amount=unit_price),
        )
        self.add_line_items(item)
        return item

    def remove_item(self, product_id):
        """Remove a line item by product_id."""
        item = next((i for i in self.line_items if i.product_id == product_id), None)
        if item is None:
            raise ValueError(f"No item with product_id '{product_id}'")
        self.remove_line_items(item)

    @property
    def total(self) -> Money:
        """Order total, folded with `Money.add()`.

        The fold is what holds an order to one currency. An `@invariant.post`
        cannot do it: `HasMany.add()` caches the item and then calls
        `_postcheck()`, and it does not undo the cache when the check raises,
        so a caller who catches the error still holds the item the rule
        rejected. `Money.add()` refuses across currencies, so an order holding
        two of them produces no total at all.
        """
        if not self.line_items:
            return Money(amount=0.0)
        running = Money(amount=0.0, currency=self.line_items[0].unit_price.currency)
        for item in self.line_items:
            running = running.add(
                Money(amount=item.subtotal, currency=item.unit_price.currency)
            )
        return running

    def place(self):
        """Place the order. Raises OrderPlaced event.

        Business rules:
        - Order must have items (enforced by invariant)
        - Order must be in draft status

        Builds the event before it touches `status`. Both steps can fail:
        `total` refuses an order holding two currencies, and the event rejects
        a missing field. Either one after the status changed would leave the
        order placed with no `OrderPlaced` event, and a retry would then be
        rejected for being placed already.
        """
        if self.status != "draft":
            raise ValueError(f"Cannot place order in '{self.status}' status")

        event = OrderPlaced(
            order_id=self.id,
            customer_id=self.customer_id,
            item_count=len(self.line_items),
            total_amount=self.total.amount,
        )
        self.status = "placed"
        self.raise_(event)

    def cancel(self, reason):
        """Cancel the order. Raises OrderCancelled event.

        Business rule: only placed orders can be cancelled.

        Builds the event first, same as `place()`. `reason` is required, so an
        empty one fails here; building after the status changed would leave the
        order cancelled with no `OrderCancelled` event.
        """
        if self.status != "placed":
            raise ValueError(f"Cannot cancel order in '{self.status}' status")

        event = OrderCancelled(order_id=self.id, reason=reason)
        self.status = "cancelled"
        self.raise_(event)
