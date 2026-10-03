# --8<-- [start:events]
from bookshelf import domain
from protean.fields import Float, Identifier, String


@domain.event(part_of="Book")
class BookAdded:
    book_id: Identifier(required=True)
    title: String(max_length=200, required=True)
    author: String(max_length=150, required=True)
    price_amount: Float()


@domain.event(part_of="Book")
class BookPriceUpdated:
    book_id: Identifier(required=True)
    new_price: Float(required=True)


@domain.event(part_of="Order")
class OrderConfirmed:
    order_id: Identifier(required=True)
    customer_name: String(max_length=150, required=True)


@domain.event(part_of="Order")
class OrderShipped:
    order_id: Identifier(required=True)
    customer_name: String(max_length=150, required=True)


# --8<-- [end:events]
