# --8<-- [start:projections]
from bookshelf import domain
from bookshelf.events import BookAdded, BookPriceUpdated
from bookshelf.models import Book
from protean.core.projector import on
from protean.fields import Float, Identifier, String
from protean.utils.globals import current_domain


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
