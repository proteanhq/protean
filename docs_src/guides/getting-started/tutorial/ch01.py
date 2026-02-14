from protean import Domain
from typing import Annotated
from pydantic import Field

domain = Domain()


# --8<-- [start:aggregate]
@domain.aggregate
class Book:
    title: Annotated[str, Field(max_length=200)]
    author: Annotated[str, Field(max_length=150)]
    isbn: Annotated[str, Field(max_length=13)] | None = None
    price: float | None = None


# --8<-- [end:aggregate]


domain.init(traverse=False)


# --8<-- [start:usage]
if __name__ == "__main__":
    with domain.domain_context():
        # Create a book
        book = Book(
            title="The Great Gatsby",
            author="F. Scott Fitzgerald",
            isbn="9780743273565",
            price=12.99,
        )
        print(f"Created: {book.title} by {book.author}")
        print(f"ID: {book.id}")

        # Persist it
        repo = domain.repository_for(Book)
        repo.add(book)

        # Retrieve it
        saved_book = repo.get(book.id)
        print(f"Retrieved: {saved_book.title} (${saved_book.price})")

        # Verify
        assert saved_book.title == "The Great Gatsby"
        assert saved_book.author == "F. Scott Fitzgerald"
        assert saved_book.price == 12.99
        print("All checks passed!")
# --8<-- [end:usage]
