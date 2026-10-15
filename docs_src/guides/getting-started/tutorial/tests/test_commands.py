# --8<-- [start:full]
from bookshelf.commands import AddBook
from bookshelf.models import Book, Inventory

from protean.utils.globals import current_domain


def test_add_book_command():
    book_id = current_domain.process(
        AddBook(
            title="The Great Gatsby",
            author="F. Scott Fitzgerald",
            price_amount=12.99,
        ),
        asynchronous=False,
    )

    book = current_domain.repository_for(Book).get(book_id)
    assert book.title == "The Great Gatsby"
    assert book.price.amount == 12.99


def test_add_book_raises_event():
    current_domain.process(
        AddBook(
            title="Dune",
            author="Frank Herbert",
            price_amount=15.99,
        ),
        asynchronous=False,
    )

    # With sync processing, the event handler runs immediately
    inventories = current_domain.repository_for(Inventory).query.all()
    assert inventories.total == 1


# --8<-- [end:full]
