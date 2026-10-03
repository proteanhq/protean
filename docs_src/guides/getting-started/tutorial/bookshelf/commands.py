# --8<-- [start:commands]
from bookshelf import domain
from bookshelf.models import Book, Order
from protean.fields import Float, Identifier, Integer, String, Text


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
