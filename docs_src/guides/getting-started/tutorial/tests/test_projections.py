# --8<-- [start:full]
from bookshelf.models import Book, Money
from bookshelf.projections import BookCatalog

from protean.utils.globals import current_domain


def test_book_catalog_projection():
    """Adding a book should create a catalog entry."""
    book = Book(
        title="Dune",
        author="Frank Herbert",
        price=Money(amount=15.99),
    )
    book.add_to_catalog()
    current_domain.repository_for(Book).add(book)

    entries = current_domain.view_for(BookCatalog).query.all()
    assert entries.total == 1
    assert entries.items[0].title == "Dune"


# --8<-- [end:full]
