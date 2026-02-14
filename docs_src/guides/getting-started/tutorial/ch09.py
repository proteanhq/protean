from protean import Domain, use_case
from protean.fields import ValueObject
from protean.utils.globals import current_domain
from typing import Annotated
from pydantic import Field

domain = Domain()

domain.config["command_processing"] = "sync"
domain.config["event_processing"] = "sync"


@domain.value_object
class Money:
    currency: Annotated[str, Field(max_length=3)] = "USD"
    amount: float


@domain.aggregate
class Book:
    title: Annotated[str, Field(max_length=200)]
    author: Annotated[str, Field(max_length=150)]
    isbn: Annotated[str, Field(max_length=13)] | None = None
    price = ValueObject(Money)
    description: str | None = None

    def add_to_catalog(self):
        self.raise_(
            BookAdded(
                book_id=self.id,
                title=self.title,
                author=self.author,
                price_amount=self.price.amount if self.price else 0,
            )
        )


@domain.event(part_of=Book)
class BookAdded:
    book_id: str
    title: Annotated[str, Field(max_length=200)]
    author: Annotated[str, Field(max_length=150)]
    price_amount: float | None = None


# --8<-- [start:catalog_service]
@domain.application_service(part_of=Book)
class CatalogService:
    @use_case
    def add_book(
        self,
        title: str,
        author: str,
        isbn: str = None,
        price_amount: float = 0.0,
        description: str = "",
    ) -> str:
        """Add a new book to the catalog."""
        book = Book(
            title=title,
            author=author,
            isbn=isbn,
            price=Money(amount=price_amount),
            description=description,
        )
        book.add_to_catalog()
        current_domain.repository_for(Book).add(book)
        return book.id

    @use_case
    def get_book(self, book_id: str) -> Book:
        """Retrieve a book by its ID."""
        return current_domain.repository_for(Book).get(book_id)

    @use_case
    def search_books(self, **filters) -> list:
        """Search for books matching the given filters."""
        query = current_domain.repository_for(Book)._dao.query
        for field, value in filters.items():
            query = query.filter(**{field: value})
        return query.all().items


# --8<-- [end:catalog_service]


domain.init(traverse=False)


# --8<-- [start:usage]
if __name__ == "__main__":
    with domain.domain_context():
        catalog = CatalogService()

        # Add books through the application service
        print("=== Adding Books via CatalogService ===")
        id1 = catalog.add_book(
            title="The Great Gatsby",
            author="F. Scott Fitzgerald",
            isbn="9780743273565",
            price_amount=12.99,
            description="A story of the mysteriously wealthy Jay Gatsby.",
        )
        print(f"Added: The Great Gatsby (ID: {id1})")

        id2 = catalog.add_book(
            title="Brave New World",
            author="Aldous Huxley",
            isbn="9780060850524",
            price_amount=14.99,
        )
        print(f"Added: Brave New World (ID: {id2})")

        id3 = catalog.add_book(
            title="1984",
            author="George Orwell",
            isbn="9780451524935",
            price_amount=11.99,
        )
        print(f"Added: 1984 (ID: {id3})")

        # Get a specific book
        print("\n=== Retrieving a Book ===")
        book = catalog.get_book(id1)
        print(f"Found: {book.title} by {book.author}, ${book.price.amount}")

        # Search for books by author
        print("\n=== Searching Books ===")
        all_books = catalog.search_books()
        print(f"Total books: {len(all_books)}")
        for b in all_books:
            print(f"  - {b.title} by {b.author}")

        # Verify
        assert len(all_books) == 3
        assert book.title == "The Great Gatsby"
        print("\nAll checks passed!")
# --8<-- [end:usage]
