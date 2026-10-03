# --8<-- [start:models]
from enum import Enum

from bookshelf import domain
from bookshelf.events import (
    BookAdded,
    BookPriceUpdated,
    OrderConfirmed,
    OrderShipped,
)
from protean.fields import (
    Float,
    HasMany,
    Identifier,
    Integer,
    String,
    Text,
    ValueObject,
)


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
