from enum import Enum

from protean import Domain
from protean.fields import (
    Float,
    HasMany,
    Integer,
    String,
    Text,
    ValueObject,
)

domain = Domain()


@domain.value_object
class Money:
    currency = String(max_length=3, default="USD")
    amount = Float(required=True)


@domain.value_object
class Address:
    street = String(max_length=200, required=True)
    city = String(max_length=100, required=True)
    state = String(max_length=50)
    zip_code = String(max_length=20, required=True)
    country = String(max_length=50, default="US")


@domain.aggregate
class Book:
    title = String(max_length=200, required=True)
    author = String(max_length=150, required=True)
    isbn = String(max_length=13)
    price = ValueObject(Money)
    description = Text()


class OrderStatus(Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"


# --8<-- [start:order_aggregate]
@domain.aggregate
class Order:
    customer_name = String(max_length=150, required=True)
    customer_email = String(max_length=254, required=True)
    shipping_address = ValueObject(Address)
    status = String(
        max_length=20, choices=OrderStatus, default=OrderStatus.PENDING.value
    )
    items = HasMany("OrderItem")


# --8<-- [end:order_aggregate]


# --8<-- [start:order_item_entity]
@domain.entity(part_of=Order)
class OrderItem:
    book_title = String(max_length=200, required=True)
    quantity = Integer(required=True)
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
