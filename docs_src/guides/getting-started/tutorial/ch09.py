# Chapter 9: Structuring the Project
# This file shows the contents of each module after restructuring.

# --8<-- [start:domain_init]
# bookshelf/__init__.py
from protean import Domain

domain = Domain("bookshelf")
# --8<-- [end:domain_init]


# --8<-- [start:models]
# bookshelf/models.py
from enum import Enum

from protean.fields import (
    Float,
    HasMany,
    Identifier,
    Integer,
    String,
    Text,
    ValueObject,
)

from bookshelf import domain


@domain.value_object
class Money:
    currency: String(max_length=3, default="USD")
    amount: Float(required=True)


@domain.value_object
class Address:
    street: String(max_length=200)
    city: String(max_length=100)
    state: String(max_length=50)
    zip_code: String(max_length=10)
    country: String(max_length=50, default="US")


class OrderStatus(Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    SHIPPED = "SHIPPED"


@domain.aggregate
class Book:
    title: String(max_length=200, required=True)
    author: String(max_length=150, required=True)
    isbn: String(max_length=13)
    price = ValueObject(Money)
    description: Text()

    def add_to_catalog(self):
        self.raise_(
            BookAdded(
                book_id=self.id,
                title=self.title,
                author=self.author,
                price_amount=self.price.amount if self.price else 0,
            )
        )

    def update_price(self, new_price: float):
        self.price = Money(amount=new_price)
        self.raise_(BookPriceUpdated(book_id=self.id, new_price=new_price))


@domain.aggregate
class Order:
    customer_name: String(max_length=150, required=True)
    status: String(
        max_length=20, choices=OrderStatus, default=OrderStatus.PENDING.value
    )
    items = HasMany("OrderItem")

    def confirm(self):
        self.status = OrderStatus.CONFIRMED.value
        self.raise_(OrderConfirmed(order_id=self.id, customer_name=self.customer_name))

    def ship(self):
        self.status = OrderStatus.SHIPPED.value
        self.raise_(OrderShipped(order_id=self.id, customer_name=self.customer_name))


@domain.entity(part_of=Order)
class OrderItem:
    book_title: String(max_length=200, required=True)
    quantity: Integer(required=True)
    unit_price = ValueObject(Money)


@domain.aggregate
class Inventory:
    book_id: Identifier(required=True)
    title: String(max_length=200, required=True)
    quantity: Integer(default=0)

    def adjust_stock(self, amount: int):
        self.quantity += amount


# --8<-- [end:models]


# --8<-- [start:events]
# bookshelf/events.py
from protean.fields import Float, Identifier, String

from bookshelf import domain
from bookshelf.models import Book, Order


@domain.event(part_of=Book)
class BookAdded:
    book_id: Identifier(required=True)
    title: String(max_length=200, required=True)
    author: String(max_length=150, required=True)
    price_amount: Float()


@domain.event(part_of=Book)
class BookPriceUpdated:
    book_id: Identifier(required=True)
    new_price: Float(required=True)


@domain.event(part_of=Order)
class OrderConfirmed:
    order_id: Identifier(required=True)
    customer_name: String(max_length=150, required=True)


@domain.event(part_of=Order)
class OrderShipped:
    order_id: Identifier(required=True)
    customer_name: String(max_length=150, required=True)


# --8<-- [end:events]


# --8<-- [start:commands]
# bookshelf/commands.py
from protean.fields import Float, Identifier, Integer, String, Text

from bookshelf import domain
from bookshelf.models import Book, Order


@domain.command(part_of=Book)
class AddBook:
    title: String(max_length=200, required=True)
    author: String(max_length=150, required=True)
    isbn: String(max_length=13)
    price_amount: Float(required=True)
    description: Text()


@domain.command(part_of=Order)
class PlaceOrder:
    customer_name: String(max_length=150, required=True)
    book_title: String(max_length=200, required=True)
    quantity: Integer(required=True)
    unit_price_amount: Float(required=True)


@domain.command(part_of=Order)
class ConfirmOrder:
    order_id: Identifier(required=True)


@domain.command(part_of=Order)
class ShipOrder:
    order_id: Identifier(required=True)


# --8<-- [end:commands]


# --8<-- [start:handlers]
# bookshelf/handlers.py
from protean import handle
from protean.fields import Identifier
from protean.utils.globals import current_domain

from bookshelf import domain
from bookshelf.commands import AddBook, ConfirmOrder, PlaceOrder, ShipOrder
from bookshelf.events import BookAdded, OrderConfirmed, OrderShipped
from bookshelf.models import Book, Inventory, Money, Order, OrderItem


@domain.command_handler(part_of=Book)
class BookCommandHandler:
    @handle(AddBook)
    def add_book(self, command: AddBook) -> Identifier:
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


@domain.command_handler(part_of=Order)
class OrderCommandHandler:
    @handle(PlaceOrder)
    def place_order(self, command: PlaceOrder) -> Identifier:
        order = Order(
            customer_name=command.customer_name,
            items=[
                OrderItem(
                    book_title=command.book_title,
                    quantity=command.quantity,
                    unit_price=Money(amount=command.unit_price_amount),
                ),
            ],
        )
        current_domain.repository_for(Order).add(order)
        return order.id

    @handle(ConfirmOrder)
    def confirm_order(self, command: ConfirmOrder) -> None:
        repo = current_domain.repository_for(Order)
        order = repo.get(command.order_id)
        order.confirm()
        repo.add(order)

    @handle(ShipOrder)
    def ship_order(self, command: ShipOrder) -> None:
        repo = current_domain.repository_for(Order)
        order = repo.get(command.order_id)
        order.ship()
        repo.add(order)


@domain.event_handler(part_of=Book)
class BookEventHandler:
    @handle(BookAdded)
    def on_book_added(self, event: BookAdded):
        inventory = Inventory(
            book_id=event.book_id,
            title=event.title,
            quantity=10,
        )
        current_domain.repository_for(Inventory).add(inventory)


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


# --8<-- [end:handlers]


# --8<-- [start:projections]
# bookshelf/projections.py
from protean.core.projector import on
from protean.fields import Float, Identifier, String

from bookshelf import domain
from bookshelf.events import BookAdded, BookPriceUpdated
from bookshelf.models import Book


@domain.projection
class BookCatalog:
    book_id: Identifier(identifier=True, required=True)
    title: String(max_length=200, required=True)
    author: String(max_length=150, required=True)
    price: Float()
    isbn: String(max_length=13)


@domain.projector(projector_for=BookCatalog, aggregates=[Book])
class BookCatalogProjector:
    @on(BookAdded)
    def on_book_added(self, event: BookAdded):
        catalog_entry = BookCatalog(
            book_id=event.book_id,
            title=event.title,
            author=event.author,
            price=event.price_amount,
            isbn=getattr(event, "isbn", ""),
        )
        current_domain.repository_for(BookCatalog).add(catalog_entry)

    @on(BookPriceUpdated)
    def on_price_updated(self, event: BookPriceUpdated):
        repo = current_domain.repository_for(BookCatalog)
        entry = repo.get(event.book_id)
        entry.price = event.new_price
        repo.add(entry)


# --8<-- [end:projections]
