from enum import Enum

from protean import Domain, invariant
from protean.exceptions import ValidationError
from protean.fields import HasMany, ValueObject
from typing import Annotated
from pydantic import Field

domain = Domain()


@domain.value_object
class Money:
    currency: Annotated[str, Field(max_length=3)] = "USD"
    amount: float


class OrderStatus(Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"


# --8<-- [start:aggregate]
@domain.aggregate
class Order:
    customer_name: Annotated[str, Field(max_length=150)]
    status: Annotated[OrderStatus, Field(max_length=20)] = OrderStatus.PENDING.value
    items = HasMany("OrderItem")

    def add_item(self, book_title: str, quantity: int, unit_price: Money):
        """Add an item to this order."""
        self.add_items(
            OrderItem(
                book_title=book_title,
                quantity=quantity,
                unit_price=unit_price,
            )
        )

    def confirm(self):
        """Confirm the order for processing."""
        self.status = OrderStatus.CONFIRMED.value

    def ship(self):
        """Mark the order as shipped."""
        self.status = OrderStatus.SHIPPED.value

    @invariant.post
    def order_must_have_items(self):
        if not self.items or len(self.items) == 0:
            raise ValidationError(
                {"_entity": ["An order must contain at least one item"]}
            )

    @invariant.post
    def confirmed_order_must_have_multiple_items_or_quantity(self):
        if self.status == OrderStatus.CONFIRMED.value:
            total_quantity = sum(item.quantity for item in self.items)
            if total_quantity < 1:
                raise ValidationError(
                    {"_entity": ["A confirmed order must have at least 1 item"]}
                )

    @invariant.pre
    def cannot_modify_shipped_order(self):
        if self.status == OrderStatus.SHIPPED.value:
            raise ValidationError(
                {"_entity": ["Cannot modify an order that has been shipped"]}
            )


# --8<-- [end:aggregate]


@domain.entity(part_of=Order)
class OrderItem:
    book_title: Annotated[str, Field(max_length=200)]
    quantity: int
    unit_price = ValueObject(Money)


domain.init(traverse=False)


# --8<-- [start:usage]
if __name__ == "__main__":
    with domain.domain_context():
        repo = domain.repository_for(Order)

        # --- Field-level validation ---
        print("=== Field Validation ===")
        try:
            Order(customer_name="")  # required field is empty
        except ValidationError as e:
            print(f"Caught: {e.messages}")

        try:
            Order(customer_name="Alice", status="INVALID_STATUS")
        except ValidationError as e:
            print(f"Caught: {e.messages}")

        # --- Invariant: order must have items ---
        print("\n=== Post-Invariant: Must Have Items ===")
        try:
            Order(customer_name="Alice")
        except ValidationError as e:
            print(f"Caught: {e.messages}")

        # --- Using aggregate methods ---
        print("\n=== Aggregate Methods ===")
        order = Order(
            customer_name="Alice",
            items=[
                OrderItem(
                    book_title="The Great Gatsby",
                    quantity=1,
                    unit_price=Money(amount=12.99),
                ),
            ],
        )
        # Add more items using the aggregate method
        order.add_item("Brave New World", 2, Money(amount=14.99))

        print(f"Order: {order.customer_name}, {len(order.items)} items")
        print(f"Status: {order.status}")

        # Confirm the order
        order.confirm()
        print(f"After confirm: {order.status}")

        # Ship the order
        order.ship()
        print(f"After ship: {order.status}")

        # --- Pre-Invariant: cannot modify shipped order ---
        print("\n=== Pre-Invariant: Cannot Modify Shipped ===")
        try:
            order.customer_name = "Bob"  # Any mutation triggers pre-check
        except ValidationError as e:
            print(f"Caught: {e.messages}")

        print("\nAll checks passed!")
# --8<-- [end:usage]
