from protean import Domain
from protean.core.projector import on
from protean.fields import Float, Identifier, String, Text
from protean.utils.globals import current_domain

domain = Domain()

domain.config["event_processing"] = "sync"


@domain.aggregate
class Book:
    title: String(max_length=200, required=True)
    author: String(max_length=150, required=True)
    isbn: String(max_length=13)
    price: Float(default=0.0)
    description: Text()

    @classmethod
    def add_to_catalog(cls, title, author, isbn=None, price=0.0, description=""):
        book = cls(
            title=title,
            author=author,
            isbn=isbn,
            price=price,
            description=description,
        )
        book.raise_(
            BookAdded(
                book_id=book.id,
                title=book.title,
                author=book.author,
                price=price,
                isbn=isbn or "",
            )
        )
        return book

    def update_price(self, new_price: float):
        self.price = new_price
        self.raise_(
            BookPriceUpdated(
                book_id=self.id,
                new_price=new_price,
            )
        )


# --8<-- [start:events]
@domain.event(part_of=Book)
class BookAdded:
    book_id: Identifier(required=True)
    title: String(max_length=200, required=True)
    author: String(max_length=150, required=True)
    price: Float()
    isbn: String(max_length=13)


@domain.event(part_of=Book)
class BookPriceUpdated:
    book_id: Identifier(required=True)
    new_price: Float(required=True)


# --8<-- [end:events]


# --8<-- [start:projection]
@domain.projection
class BookCatalog:
    """A read-optimized view of the book catalog for browsing."""

    book_id: Identifier(identifier=True, required=True)
    title: String(max_length=200, required=True)
    author: String(max_length=150, required=True)
    price: Float()
    isbn: String(max_length=13)


# --8<-- [end:projection]


# --8<-- [start:projector]
@domain.projector(projector_for=BookCatalog, aggregates=[Book])
class BookCatalogProjector:
    """Maintains the BookCatalog projection from Book events."""

    @on(BookAdded)
    def on_book_added(self, event: BookAdded):
        catalog_entry = BookCatalog(
            book_id=event.book_id,
            title=event.title,
            author=event.author,
            price=event.price,
            isbn=event.isbn,
        )
        current_domain.repository_for(BookCatalog).add(catalog_entry)

    @on(BookPriceUpdated)
    def on_price_updated(self, event: BookPriceUpdated):
        repo = current_domain.repository_for(BookCatalog)
        entry = repo.get(event.book_id)
        entry.price = event.new_price
        repo.add(entry)


# --8<-- [end:projector]


domain.init(traverse=False)


# --8<-- [start:usage]
if __name__ == "__main__":
    with domain.domain_context():
        book_repo = domain.repository_for(Book)
        catalog_repo = domain.repository_for(BookCatalog)

        # Add books — events trigger the projector
        print("=== Adding Books ===")
        gatsby = Book.add_to_catalog(
            title="The Great Gatsby",
            author="F. Scott Fitzgerald",
            isbn="9780743273565",
            price=12.99,
        )
        book_repo.add(gatsby)

        brave = Book.add_to_catalog(
            title="Brave New World",
            author="Aldous Huxley",
            isbn="9780060850524",
            price=14.99,
        )
        book_repo.add(brave)

        orwell = Book.add_to_catalog(
            title="1984",
            author="George Orwell",
            isbn="9780451524935",
            price=11.99,
        )
        book_repo.add(orwell)

        # Query the projection — optimized for browsing
        print("\n=== Book Catalog (Projection) ===")
        all_entries = catalog_repo._dao.query.all()
        print(f"Total entries: {all_entries.total}")
        for entry in all_entries.items:
            print(f"  {entry.title} by {entry.author} — ${entry.price}")

        # Update a price — projector updates the catalog
        print("\n=== Updating Price ===")
        gatsby.update_price(15.99)
        book_repo.add(gatsby)

        updated_entry = catalog_repo.get(gatsby.id)
        print(f"Updated: {updated_entry.title} — ${updated_entry.price}")

        # Verify
        assert all_entries.total == 3
        assert updated_entry.price == 15.99
        print("\nAll checks passed!")
# --8<-- [end:usage]
