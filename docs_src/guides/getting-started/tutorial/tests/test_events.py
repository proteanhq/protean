# --8<-- [start:full]
from bookshelf.models import Book, Inventory, Money

from protean.utils.globals import current_domain


def test_book_added_creates_inventory():
    """When a book is added, an inventory record should be created."""
    book = Book(
        title="1984",
        author="George Orwell",
        price=Money(amount=11.99),
    )
    book.add_to_catalog()
    current_domain.repository_for(Book).add(book)

    inventories = current_domain.repository_for(Inventory).query.all()
    assert inventories.total == 1
    assert inventories.items[0].title == "1984"


# --8<-- [end:full]
