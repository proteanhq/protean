"""
Layer 3: Aggregate Invariants

This example demonstrates:
- @invariant.post for consistency rules checked after state changes
- @invariant.pre for state guards checked before state changes
- Cross-field validation within aggregates
- Collection constraints (items must match totals)
- State machine guards (prevent invalid transitions)
- Entity-level invariants within an aggregate

Scenario:
    An Order aggregate with line items demonstrates:
    - Total must equal sum of item subtotals (post-invariant)
    - Cannot modify a shipped order (pre-invariant)
    - Entity-level invariant on OrderItem (quantity must be positive)

Usage:
    order = Order(
        order_id="ORD-001",
        customer_name="Jane Doe",
        status="draft",
        total_amount=100.0,
        items=[
            OrderItem(product_name="Widget", quantity=4, price=10.0, subtotal=40.0),
            OrderItem(product_name="Gadget", quantity=3, price=20.0, subtotal=60.0),
        ],
    )
"""

from protean import Domain, invariant
from protean.exceptions import ValidationError
from protean.fields import Float, HasMany, Integer, String

# Domain setup
domain = Domain(__name__)


@domain.aggregate
class Order:
    """Order aggregate with pre and post invariants.

    Demonstrates Layer 3 validation:
    - Post-invariant: total_amount must equal sum of item subtotals
    - Post-invariant: placed orders must have at least one item
    - Pre-invariant: shipped orders cannot be modified
    """

    order_id: String(required=True, max_length=20, identifier=True)
    customer_name: String(required=True, max_length=100)
    status: String(max_length=20, default="draft")
    total_amount: Float(default=0.0)
    items = HasMany("OrderItem")

    # --- POST-INVARIANTS: checked after initialization and attribute changes ---

    @invariant.post
    def total_must_equal_sum_of_items(self):
        """Order total must match sum of item subtotals."""
        if self.items:
            expected = sum(item.subtotal for item in self.items)
            if self.total_amount != expected:
                raise ValidationError(
                    {
                        "_entity": [
                            f"Total amount ({self.total_amount}) must equal "
                            f"sum of item subtotals ({expected})"
                        ]
                    }
                )

    @invariant.post
    def must_have_items_when_placed(self):
        """Placed or shipped orders must have at least one item."""
        if self.status in ("placed", "shipped") and not self.items:
            raise ValidationError(
                {"items": ["Order must have at least one item when placed"]}
            )

    # --- PRE-INVARIANT: checked before attribute changes (not on init) ---

    @invariant.pre
    def cannot_modify_shipped_order(self):
        """Shipped orders are immutable — no further changes allowed."""
        if self.status == "shipped":
            raise ValidationError({"_entity": ["Cannot modify a shipped order"]})

    # --- Business methods ---

    def place(self):
        """Transition order to placed status."""
        self.status = "placed"

    def ship(self):
        """Transition order to shipped status."""
        self.status = "shipped"


@domain.entity(part_of="Order")
class OrderItem:
    """Order line item with entity-level invariants.

    Entity invariants also run as part of the aggregate's validation chain.
    """

    product_name: String(required=True, max_length=100)
    quantity: Integer(required=True)
    price: Float(required=True)
    subtotal: Float(required=True)

    @invariant.post
    def quantity_must_be_positive(self):
        """Quantity must be at least 1."""
        if self.quantity <= 0:
            raise ValidationError({"quantity": ["Quantity must be positive"]})

    @invariant.post
    def subtotal_must_match_quantity_times_price(self):
        """Subtotal must equal quantity * price."""
        expected = self.quantity * self.price
        if self.subtotal != expected:
            raise ValidationError(
                {
                    "subtotal": [
                        f"Subtotal ({self.subtotal}) must equal "
                        f"quantity ({self.quantity}) x price ({self.price}) = {expected}"
                    ]
                }
            )


if __name__ == "__main__":  # pragma: no cover
    domain.init(traverse=False)
    with domain.domain_context():
        # Valid order with items
        order = Order(
            order_id="ORD-001",
            customer_name="Jane Doe",
            status="draft",
            total_amount=100.0,
            items=[
                OrderItem(product_name="Widget", quantity=4, price=10.0, subtotal=40.0),
                OrderItem(product_name="Gadget", quantity=3, price=20.0, subtotal=60.0),
            ],
        )
        print(f"Order: {order.order_id}, Total: ${order.total_amount}")

        # Invalid: total doesn't match items
        try:
            Order(
                order_id="ORD-002",
                customer_name="Bad Total",
                total_amount=999.0,
                items=[
                    OrderItem(
                        product_name="Widget", quantity=2, price=10.0, subtotal=20.0
                    ),
                ],
            )
        except ValidationError as e:
            print(f"Total mismatch: {e}")

        # Invalid: zero quantity
        try:
            OrderItem(product_name="Widget", quantity=0, price=10.0, subtotal=0.0)
        except ValidationError as e:
            print(f"Bad quantity: {e}")
