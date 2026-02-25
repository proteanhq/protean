# --8<-- [start:full]
from protean import Domain, handle
from protean.fields import Float, Identifier, Integer, String
from protean.utils.globals import current_domain

domain = Domain("bookshelf")
domain.config["command_processing"] = "sync"
domain.config["event_processing"] = "sync"


@domain.aggregate
class Book:
    title: String(max_length=200, required=True)
    author: String(max_length=150, required=True)
    isbn: String(max_length=13)
    price: Float(default=0.0)


@domain.aggregate
class Inventory:
    book_id: Identifier(required=True)
    title: String(max_length=200, required=True)
    quantity: Integer(default=0)

    def adjust_stock(self, amount: int):
        self.quantity += amount


@domain.command(part_of=Book)
class AddBook:
    title: String(max_length=200, required=True)
    author: String(max_length=150, required=True)
    isbn: String(max_length=13)
    price_amount: Float(required=True)


# --8<-- [start:restock_command]
@domain.command(part_of=Inventory)
class RestockInventory:
    book_id: Identifier(required=True)
    quantity: Integer(required=True)


# --8<-- [end:restock_command]


# --8<-- [start:restock_handler]
@domain.command_handler(part_of=Inventory)
class InventoryCommandHandler:
    @handle(RestockInventory)
    def restock(self, command: RestockInventory) -> None:
        repo = current_domain.repository_for(Inventory)
        inventory = repo.get(command.book_id)
        inventory.adjust_stock(command.quantity)
        repo.add(inventory)


# --8<-- [end:restock_handler]


# --8<-- [start:subscriber]
@domain.subscriber(stream="book_supply")
class BookSupplyWebhookSubscriber:
    """Consumes messages from the BookSupply distributor and translates
    them into domain operations."""

    def __call__(self, payload: dict) -> None:
        event_type = payload.get("event_type")

        if event_type == "new_book_available":
            current_domain.process(
                AddBook(
                    title=payload["title"],
                    author=payload["author"],
                    isbn=payload.get("isbn"),
                    price_amount=payload["price"],
                )
            )

        elif event_type == "stock_replenished":
            current_domain.process(
                RestockInventory(
                    book_id=payload["book_id"],
                    quantity=payload["quantity"],
                )
            )


# --8<-- [end:subscriber]


domain.init(traverse=False)


# --8<-- [start:tests]
# tests/test_subscribers.py (example tests)


def test_new_book_available_webhook():
    """External 'new_book_available' message creates a book."""
    subscriber = BookSupplyWebhookSubscriber()
    subscriber(
        {
            "event_type": "new_book_available",
            "title": "War and Peace",
            "author": "Leo Tolstoy",
            "isbn": "9780199232765",
            "price": 18.99,
        }
    )

    # Verify the book was created
    books = current_domain.repository_for(Book).query.all()
    assert books.total >= 1


# --8<-- [end:tests]
# --8<-- [end:full]
