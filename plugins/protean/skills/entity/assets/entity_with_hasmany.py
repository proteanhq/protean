"""
Entity with HasMany relationship (one-to-many).

This example demonstrates:
- Entity with HasMany association to other entities
- One-to-many relationship between entities
- Adding and removing child entities
- Iterating over child entities
- Computed properties based on child entities
- Business logic spanning parent and child entities

Usage:
    order = Order(customer_id="C123")
    item = LineItem(product_id="P1", quantity=2, unit_price=50.0)
    order.add_line_items([item])
    domain.repository_for(Order).add(order)
"""

from protean import Domain
from protean.fields import Float, HasMany, Integer, Reference, String

# Domain setup
domain = Domain()


@domain.aggregate
class Order:
    """An order aggregate containing multiple line items."""

    order_number: String(required=True, max_length=50, unique=True)
    customer_id: String(required=True, max_length=50)
    status: String(max_length=20, default="draft")

    # One-to-many: order has many line items
    line_items = HasMany("LineItem")

    @property
    def total_amount(self) -> float:
        """Calculate total order amount from all line items."""
        if not self.line_items:
            return 0.0
        return sum(item.total for item in self.line_items)

    @property
    def total_quantity(self) -> int:
        """Calculate total quantity across all line items."""
        if not self.line_items:
            return 0
        return sum(item.quantity for item in self.line_items)

    @property
    def item_count(self) -> int:
        """Get number of line items."""
        return len(self.line_items) if self.line_items else 0

    def add_item(
        self, product_id: str, product_name: str, quantity: int, unit_price: float
    ):
        """
        Add a new line item to the order.

        Validations (quantity > 0, unit_price >= 0) are enforced by LineItem field constraints.
        """
        item = LineItem(
            product_id=product_id,
            product_name=product_name,
            quantity=quantity,
            unit_price=unit_price,
        )
        self.add_line_items([item])

    def remove_item(self, product_id: str):
        """Remove a line item by product ID."""
        item = next((i for i in self.line_items if i.product_id == product_id), None)
        if item is None:
            raise ValueError(f"Product {product_id} not found in order")
        self.remove_line_items(item)

    def update_item_quantity(self, product_id: str, new_quantity: int):
        """
        Update quantity for a specific line item.

        Validation (quantity > 0) is enforced by LineItem field constraint.
        """
        item = next((i for i in self.line_items if i.product_id == product_id), None)
        if item is None:
            raise ValueError(f"Product {product_id} not found in order")

        item.quantity = new_quantity

    def clear_items(self):
        """Remove all line items from order."""
        if self.line_items:
            # Create a copy of the list to avoid modification during iteration
            items_to_remove = list(self.line_items)
            for item in items_to_remove:
                self.remove_line_items(item)

    def place(self):
        """Place the order."""
        if not self.line_items:
            raise ValueError("Cannot place order without line items")
        self.status = "placed"


@domain.entity(part_of="Order")
class LineItem:
    """A line item entity representing a product in an order."""

    product_id: String(required=True, max_length=50)
    product_name: String(required=True, max_length=200)
    quantity: Integer(required=True, min_value=1)
    unit_price: Float(required=True, min_value=0.0)
    discount_percent: Float(min_value=0.0, max_value=100.0, default=0.0)

    # Reference back to parent aggregate (automatic)
    order = Reference(Order)

    @property
    def subtotal(self) -> float:
        """Calculate subtotal before discount."""
        return self.quantity * self.unit_price

    @property
    def discount_amount(self) -> float:
        """Calculate discount amount."""
        return self.subtotal * (self.discount_percent / 100.0)

    @property
    def total(self) -> float:
        """Calculate total after discount."""
        return self.subtotal - self.discount_amount

    def apply_discount(self, percent: float):
        """Apply a discount to this line item."""
        if percent < 0 or percent > 100:
            raise ValueError("Discount percent must be between 0 and 100")
        self.discount_percent = percent

    def increase_quantity(self, amount: int):
        """Increase quantity by specified amount."""
        if amount <= 0:
            raise ValueError("Amount must be positive")
        self.quantity += amount

    def decrease_quantity(self, amount: int):
        """Decrease quantity by specified amount."""
        if amount <= 0:
            raise ValueError("Amount must be positive")
        if self.quantity - amount < 1:
            raise ValueError("Resulting quantity must be at least 1")
        self.quantity -= amount


# Example usage
if __name__ == "__main__":
    domain.init(traverse=False)

    with domain.domain_context():
        # Create an order
        order = Order(
            order_number="ORD-2024-001",
            customer_id="CUST-12345",
        )

        # Add line items using helper method
        order.add_item("PROD-001", "Laptop", 1, 999.99)
        order.add_item("PROD-002", "Mouse", 2, 29.99)
        order.add_item("PROD-003", "Keyboard", 1, 79.99)

        print(f"Order: {order.order_number}")
        print(f"Customer: {order.customer_id}")
        print(f"Items: {order.item_count}")
        print(f"Total quantity: {order.total_quantity}")
        print(f"Total amount: ${order.total_amount:.2f}")

        # List all items
        print("\nLine items:")
        for item in order.line_items:
            print(f"  - {item.product_name} (x{item.quantity}): ${item.subtotal:.2f}")

        # Apply discount to first item
        order.line_items[0].apply_discount(10.0)
        print("\nAfter 10% discount on laptop:")
        print(f"  Subtotal: ${order.line_items[0].subtotal:.2f}")
        print(f"  Discount: ${order.line_items[0].discount_amount:.2f}")
        print(f"  Total: ${order.line_items[0].total:.2f}")

        # Update item quantity
        order.update_item_quantity("PROD-002", 3)
        print("\nAfter updating mouse quantity to 3:")
        print(f"  Total quantity: {order.total_quantity}")
        print(f"  Total amount: ${order.total_amount:.2f}")

        # Remove an item
        order.remove_item("PROD-003")
        print("\nAfter removing keyboard:")
        print(f"  Items: {order.item_count}")
        print(f"  Total amount: ${order.total_amount:.2f}")

        # Demonstrate bidirectional reference
        print(f"\nFirst item's order number: {order.line_items[0].order.order_number}")

        # Place the order
        order.place()
        print(f"\nOrder status: {order.status}")
