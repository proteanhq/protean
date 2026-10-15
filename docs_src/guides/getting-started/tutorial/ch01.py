# --8<-- [start:full]
# --8<-- [start:imports_and_aggregate]
# --8<-- [start:domain_import]
from protean import Domain

# --8<-- [end:domain_import]
from protean.fields import Float, String

# --8<-- [start:domain_instance]
domain = Domain()
# --8<-- [end:domain_instance]


# --8<-- [start:aggregate]
@domain.aggregate
class Book:
    title: String(max_length=200, required=True)
    author: String(max_length=150, required=True)
    isbn: String(max_length=13)
    price: Float()


# --8<-- [end:aggregate]
# --8<-- [end:imports_and_aggregate]


# --8<-- [start:create_book]
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
        # --8<-- [end:create_book]

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
# --8<-- [end:full]
