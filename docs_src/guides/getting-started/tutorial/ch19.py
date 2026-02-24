# --8<-- [start:full]
import csv

from protean import Domain
from protean.fields import Float, String, Text
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


domain.init(traverse=False)


# --8<-- [start:import_script]
# import_vintage_press.py
def import_catalog(csv_path: str):
    """Import the Vintage Press catalog with BULK priority."""
    with domain.domain_context():
        with processing_priority(Priority.BULK):
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
