from enum import Enum

from protean import Domain
from protean.fields import HasMany, ValueObject
from typing import Annotated
from pydantic import Field

domain = Domain()


@domain.value_object
class Money:
    currency: Annotated[str, Field(max_length=3)] = "USD"
    amount: float


@domain.value_object
class Address:
    street: Annotated[str, Field(max_length=200)]
    city: Annotated[str, Field(max_length=100)]
    state: Annotated[str, Field(max_length=50)] | None = None
    zip_code: Annotated[str, Field(max_length=20)]
    country: Annotated[str, Field(max_length=50)] = "US"


@domain.aggregate
class Book:
    title: Annotated[str, Field(max_length=200)]
    author: Annotated[str, Field(max_length=150)]
    isbn: Annotated[str, Field(max_length=13)] | None = None
    price = ValueObject(Money)
    description: str | None = None


class OrderStatus(Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"


# --8<-- [start:order_aggregate]
@domain.aggregate
class Order:
    customer_name: Annotated[str, Field(max_length=150)]
    customer_email: Annotated[str, Field(max_length=254)]
    shipping_address = ValueObject(Address)
    status: Annotated[OrderStatus, Field(max_length=20)] = OrderStatus.PENDING.value
    items = HasMany("OrderItem")


# --8<-- [end:order_aggregate]


# --8<-- [start:order_item_entity]
@domain.entity(part_of=Order)
class OrderItem:
    book_title: Annotated[str, Field(max_length=200)]
    quantity: int
    unit_price = ValueObject(Money)


# --8<-- [end:order_item_entity]


domain.init(traverse=False)


# --8<-- [start:usage]
if __name__ == "__main__":
    with domain.domain_context():
        repo = domain.repository_for(Order)

        # Create an order with items
        order = Order(
            customer_name="Alice Johnson",
            customer_email="alice@example.com",
            shipping_address=Address(
                street="456 Oak Ave",
                city="Portland",
                state="OR",
                zip_code="97201",
            ),
            items=[
                OrderItem(
                    book_title="The Great Gatsby",
                    quantity=1,
                    unit_price=Money(amount=12.99),
                ),
                OrderItem(
                    book_title="Brave New World",
                    quantity=2,
                    unit_price=Money(amount=14.99),
                ),
            ],
        )

        print(f"Order for: {order.customer_name}")
        print(f"Status: {order.status}")
        print(f"Ship to: {order.shipping_address.city}, {order.shipping_address.state}")
        print(f"Items ({len(order.items)}):")
        for item in order.items:
            print(f"  - {item.book_title} x{item.quantity} @ ${item.unit_price.amount}")
            print(f"    Item ID: {item.id}")

        # Persist the entire aggregate (order + items together)
        repo.add(order)

        # Retrieve and verify
        saved_order = repo.get(order.id)
        print(f"\nRetrieved order: {saved_order.customer_name}")
        print(f"Items: {len(saved_order.items)}")

        # Add another item to the order
        saved_order.add_items(
            OrderItem(
                book_title="Sapiens",
                quantity=1,
                unit_price=Money(amount=18.99),
            )
        )
        repo.add(saved_order)

        # Verify the update
        updated = repo.get(order.id)
        print(f"After adding item: {len(updated.items)} items")

        # Verify
        assert updated.customer_name == "Alice Johnson"
        assert len(updated.items) == 3
        assert updated.shipping_address.city == "Portland"
        print("\nAll checks passed!")
# --8<-- [end:usage]
