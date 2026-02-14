from enum import Enum

from protean import Domain, handle
from protean.fields import HasMany, ValueObject
from protean.utils.globals import current_domain
from typing import Annotated
from pydantic import Field

domain = Domain()

domain.config["command_processing"] = "sync"
domain.config["event_processing"] = "sync"


@domain.value_object
class Money:
    currency: Annotated[str, Field(max_length=3)] = "USD"
    amount: float


# --8<-- [start:book_aggregate]
@domain.aggregate
class Book:
    title: Annotated[str, Field(max_length=200)]
    author: Annotated[str, Field(max_length=150)]
    isbn: Annotated[str, Field(max_length=13)] | None = None
    price = ValueObject(Money)
    description: str | None = None

    def add_to_catalog(self):
        """Mark this book as added to the catalog and raise an event."""
        self.raise_(
            BookAdded(
                book_id=self.id,
                title=self.title,
                author=self.author,
                price_amount=self.price.amount if self.price else 0,
                price_currency=self.price.currency if self.price else "USD",
            )
        )


# --8<-- [end:book_aggregate]


# --8<-- [start:book_event]
@domain.event(part_of=Book)
class BookAdded:
    book_id: str
    title: Annotated[str, Field(max_length=200)]
    author: Annotated[str, Field(max_length=150)]
    price_amount: float | None = None
    price_currency: Annotated[str, Field(max_length=3)] = "USD"


# --8<-- [end:book_event]


class OrderStatus(Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    SHIPPED = "SHIPPED"


# --8<-- [start:order_aggregate]
@domain.aggregate
class Order:
    customer_name: Annotated[str, Field(max_length=150)]
    status: Annotated[OrderStatus, Field(max_length=20)] = OrderStatus.PENDING.value
    items = HasMany("OrderItem")

    def confirm(self):
        self.status = OrderStatus.CONFIRMED.value
        self.raise_(
            OrderConfirmed(
                order_id=self.id,
                customer_name=self.customer_name,
            )
        )

    def ship(self):
        self.status = OrderStatus.SHIPPED.value
        self.raise_(
            OrderShipped(
                order_id=self.id,
                customer_name=self.customer_name,
            )
        )


# --8<-- [end:order_aggregate]


@domain.entity(part_of=Order)
class OrderItem:
    book_title: Annotated[str, Field(max_length=200)]
    quantity: int
    unit_price = ValueObject(Money)


# --8<-- [start:order_events]
@domain.event(part_of=Order)
class OrderPlaced:
    order_id: str
    customer_name: Annotated[str, Field(max_length=150)]
    total_items: int


@domain.event(part_of=Order)
class OrderConfirmed:
    order_id: str
    customer_name: Annotated[str, Field(max_length=150)]


@domain.event(part_of=Order)
class OrderShipped:
    order_id: str
    customer_name: Annotated[str, Field(max_length=150)]


# --8<-- [end:order_events]


@domain.command(part_of=Book)
class AddBook:
    title: Annotated[str, Field(max_length=200)]
    author: Annotated[str, Field(max_length=150)]
    isbn: Annotated[str, Field(max_length=13)] | None = None
    price_amount: float
    price_currency: Annotated[str, Field(max_length=3)] = "USD"
    description: str | None = None


# --8<-- [start:book_handler]
@domain.command_handler(part_of=Book)
class BookCommandHandler:
    @handle(AddBook)
    def add_book(self, command: AddBook) -> str:
        book = Book(
            title=command.title,
            author=command.author,
            isbn=command.isbn,
            price=Money(
                amount=command.price_amount,
                currency=command.price_currency,
            ),
            description=command.description,
        )
        book.add_to_catalog()  # Raises BookAdded event
        current_domain.repository_for(Book).add(book)
        return book.id


# --8<-- [end:book_handler]


domain.init(traverse=False)


# --8<-- [start:usage]
if __name__ == "__main__":
    with domain.domain_context():
        # Add a book — triggers BookAdded event
        book_id = domain.process(
            AddBook(
                title="The Great Gatsby",
                author="F. Scott Fitzgerald",
                isbn="9780743273565",
                price_amount=12.99,
                description="A story of the mysteriously wealthy Jay Gatsby.",
            )
        )
        print(f"Book added: {book_id}")

        # Create and confirm an order — triggers OrderConfirmed event
        repo = current_domain.repository_for(Order)
        order = Order(
            customer_name="Alice Johnson",
            items=[
                OrderItem(
                    book_title="The Great Gatsby",
                    quantity=1,
                    unit_price=Money(amount=12.99),
                ),
            ],
        )
        repo.add(order)

        # Confirm the order
        order.confirm()
        repo.add(order)
        print(f"Order confirmed: {order.id}")

        # Ship the order
        order.ship()
        repo.add(order)
        print(f"Order shipped: {order.id}")

        # Verify
        saved_order = repo.get(order.id)
        assert saved_order.status == OrderStatus.SHIPPED.value
        print("\nAll checks passed!")
# --8<-- [end:usage]
