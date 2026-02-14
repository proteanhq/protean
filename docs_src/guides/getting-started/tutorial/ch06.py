from protean import Domain, handle
from protean.fields import ValueObject
from protean.utils.globals import current_domain
from typing import Annotated
from pydantic import Field

domain = Domain()

domain.config["command_processing"] = "sync"


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


# --8<-- [start:command]
@domain.command(part_of=Book)
class AddBook:
    title: Annotated[str, Field(max_length=200)]
    author: Annotated[str, Field(max_length=150)]
    isbn: Annotated[str, Field(max_length=13)] | None = None
    price_amount: float
    price_currency: Annotated[str, Field(max_length=3)] = "USD"
    description: str | None = None


# --8<-- [end:command]


# --8<-- [start:handler]
@domain.command_handler(part_of=Book)
class BookCommandHandler:
    @handle(AddBook)
    def add_book(self, command: AddBook) -> str:
        book = Book(
            title=command.title,
            author=command.author,
            isbn=command.isbn,
            price=Money(
                amount=command.price_amount,
                currency=command.price_currency,
            ),
            description=command.description,
        )
        current_domain.repository_for(Book).add(book)
        return book.id


# --8<-- [end:handler]


domain.init(traverse=False)


# --8<-- [start:usage]
if __name__ == "__main__":
    with domain.domain_context():
        # Process a command to add a book
        book_id = domain.process(
            AddBook(
                title="The Great Gatsby",
                author="F. Scott Fitzgerald",
                isbn="9780743273565",
                price_amount=12.99,
                description="A story of the mysteriously wealthy Jay Gatsby.",
            )
        )
        print(f"Book added with ID: {book_id}")

        # The book is now in the repository
        book = current_domain.repository_for(Book).get(book_id)
        print(f"Retrieved: {book.title} by {book.author}")
        print(f"Price: ${book.price.amount} {book.price.currency}")

        # Add another book
        book_id_2 = domain.process(
            AddBook(
                title="Brave New World",
                author="Aldous Huxley",
                isbn="9780060850524",
                price_amount=14.99,
                description="A dystopian novel set in a futuristic World State.",
            )
        )

        # Verify both books exist
        all_books = current_domain.repository_for(Book)._dao.query.all()
        print(f"\nTotal books: {all_books.total}")
        for b in all_books.items:
            print(f"  - {b.title}")

        # Verify
        assert all_books.total == 2
        print("\nAll checks passed!")
# --8<-- [end:usage]
