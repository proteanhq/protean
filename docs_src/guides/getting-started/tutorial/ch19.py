# --8<-- [start:full]
import csv

from protean import Domain, handle
from protean.fields import Float, Identifier, String, Text
from protean.utils.globals import current_domain
from protean.utils.processing import Priority, processing_priority

domain = Domain("bookshelf")


@domain.aggregate
class Book:
    title: String(max_length=200, required=True)
    author: String(max_length=150, required=True)
    isbn: String(max_length=13)
    price: Float(default=0.0)
    description: Text()


@domain.command(part_of=Book)
class AddBook:
    title: String(max_length=200, required=True)
    author: String(max_length=150, required=True)
    isbn: String(max_length=13)
    price_amount: Float(required=True)
    description: Text()


@domain.event(part_of=Book)
class BookAdded:
    book_id: Identifier(required=True)
    title: String(max_length=200, required=True)


@domain.command_handler(part_of=Book)
class BookCommandHandler:
    @handle(AddBook)
    def add_book(self, command: AddBook) -> None:
        book = Book(
            title=command.title,
            author=command.author,
            isbn=command.isbn,
            price=command.price_amount,
            description=command.description,
        )
        book.raise_(BookAdded(book_id=book.id, title=book.title))
        current_domain.repository_for(Book).add(book)


domain.init(traverse=False)


# --8<-- [start:per_command]
def add_bulk_book() -> None:
    domain.process(
        AddBook(title="...", author="...", price_amount=9.99),
        priority=Priority.BULK,
    )


# --8<-- [end:per_command]
# --8<-- [start:import_script]
# import_vintage_press.py
def import_catalog(csv_path: str):
    """Import the Vintage Press catalog with BULK priority."""
    with domain.domain_context(), processing_priority(Priority.BULK):
        with open(csv_path) as f:
            reader = csv.DictReader(f)
            for i, row in enumerate(reader, 1):
                domain.process(
                    AddBook(
                        title=row["title"],
                        author=row["author"],
                        isbn=row.get("isbn", ""),
                        price_amount=float(row["price"]),
                    )
                )
                if i % 10000 == 0:
                    print(f"Progress: {i:,} books imported...")

        print(f"Import complete: {i:,} books imported with BULK priority.")


if __name__ == "__main__":
    import sys

    import_catalog(sys.argv[1])
# --8<-- [end:import_script]
# --8<-- [end:full]
