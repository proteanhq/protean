from protean import Domain, handle
from protean.fields import Float, Identifier, String, Text, ValueObject
from protean.utils.globals import current_domain

domain = Domain()

domain.config["command_processing"] = "sync"


@domain.value_object
class Money:
    currency: String(max_length=3, default="USD")
    amount: Float(required=True)


@domain.aggregate
class Book:
    title: String(max_length=200, required=True)
    author: String(max_length=150, required=True)
    isbn: String(max_length=13)
    price = ValueObject(Money)
    description: Text()


# --8<-- [start:command]
@domain.command(part_of=Book)
class AddBook:
    title: String(max_length=200, required=True)
    author: String(max_length=150, required=True)
    isbn: String(max_length=13)
    price_amount: Float(required=True)
    price_currency: String(max_length=3, default="USD")
    description: Text()


# --8<-- [end:command]


# --8<-- [start:handler]
@domain.command_handler(part_of=Book)
class BookCommandHandler:
    @handle(AddBook)
    def add_book(self, command: AddBook) -> Identifier:
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
