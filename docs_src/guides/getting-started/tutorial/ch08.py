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


@domain.aggregate
class Book:
    title: Annotated[str, Field(max_length=200)]
    author: Annotated[str, Field(max_length=150)]
    isbn: Annotated[str, Field(max_length=13)] | None = None
    price = ValueObject(Money)
    description: str | None = None

    def add_to_catalog(self):
        self.raise_(
            BookAdded(
                book_id=self.id,
                title=self.title,
                author=self.author,
                price_amount=self.price.amount if self.price else 0,
            )
        )


@domain.event(part_of=Book)
class BookAdded:
    book_id: str
    title: Annotated[str, Field(max_length=200)]
    author: Annotated[str, Field(max_length=150)]
    price_amount: float | None = None


class OrderStatus(Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    SHIPPED = "SHIPPED"


@domain.aggregate
class Order:
    customer_name: Annotated[str, Field(max_length=150)]
    status: Annotated[OrderStatus, Field(max_length=20)] = OrderStatus.PENDING.value
    items = HasMany("OrderItem")

    def confirm(self):
        self.status = OrderStatus.CONFIRMED.value
        self.raise_(OrderConfirmed(order_id=self.id, customer_name=self.customer_name))

    def ship(self):
        self.status = OrderStatus.SHIPPED.value
        self.raise_(OrderShipped(order_id=self.id, customer_name=self.customer_name))


@domain.entity(part_of=Order)
class OrderItem:
    book_title: Annotated[str, Field(max_length=200)]
    quantity: int
    unit_price = ValueObject(Money)


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


# --8<-- [start:inventory]
@domain.aggregate
class Inventory:
    book_id: str
    title: Annotated[str, Field(max_length=200)]
    quantity: int = 0

    def adjust_stock(self, amount: int):
        self.quantity += amount


# --8<-- [end:inventory]


# --8<-- [start:book_event_handler]
@domain.event_handler(part_of=Book)
class BookEventHandler:
    @handle(BookAdded)
    def on_book_added(self, event: BookAdded):
        """When a book is added to the catalog, create an inventory record."""
        inventory = Inventory(
            book_id=event.book_id,
            title=event.title,
            quantity=10,  # Start with 10 copies
        )
        current_domain.repository_for(Inventory).add(inventory)
        print(f"  [Inventory] Stocked 10 copies of '{event.title}'")


# --8<-- [end:book_event_handler]


# --8<-- [start:order_event_handler]
@domain.event_handler(part_of=Order)
class OrderEventHandler:
    @handle(OrderConfirmed)
    def on_order_confirmed(self, event: OrderConfirmed):
        print(
            f"  [Notification] Order {event.order_id} confirmed for {event.customer_name}"
        )

    @handle(OrderShipped)
    def on_order_shipped(self, event: OrderShipped):
        print(
            f"  [Notification] Order {event.order_id} shipped to {event.customer_name}"
        )


# --8<-- [end:order_event_handler]


@domain.command(part_of=Book)
class AddBook:
    title: Annotated[str, Field(max_length=200)]
    author: Annotated[str, Field(max_length=150)]
    isbn: Annotated[str, Field(max_length=13)] | None = None
    price_amount: float
    description: str | None = None


@domain.command_handler(part_of=Book)
class BookCommandHandler:
    @handle(AddBook)
    def add_book(self, command: AddBook) -> str:
        book = Book(
            title=command.title,
            author=command.author,
            isbn=command.isbn,
            price=Money(amount=command.price_amount),
            description=command.description,
        )
        book.add_to_catalog()
        current_domain.repository_for(Book).add(book)
        return book.id


domain.init(traverse=False)


# --8<-- [start:usage]
if __name__ == "__main__":
    with domain.domain_context():
        # Add a book — BookAdded event → inventory created
        print("Adding book to catalog...")
        book_id = domain.process(
            AddBook(
                title="The Great Gatsby",
                author="F. Scott Fitzgerald",
                isbn="9780743273565",
                price_amount=12.99,
            )
        )

        # Verify inventory was created by the event handler
        inventories = current_domain.repository_for(Inventory)._dao.query.all()
        assert inventories.total == 1
        inv = inventories.items[0]
        print(f"  Inventory: {inv.title}, qty={inv.quantity}")

        # Place and confirm an order
        print("\nPlacing an order...")
        order = Order(
            customer_name="Alice Johnson",
            items=[
                OrderItem(
                    book_title="The Great Gatsby",
                    quantity=2,
                    unit_price=Money(amount=12.99),
                ),
            ],
        )
        current_domain.repository_for(Order).add(order)

        print("Confirming order...")
        order.confirm()
        current_domain.repository_for(Order).add(order)

        print("Shipping order...")
        order.ship()
        current_domain.repository_for(Order).add(order)

        print("\nAll checks passed!")
# --8<-- [end:usage]
