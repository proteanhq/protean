from enum import Enum

from protean import Domain
from protean.fields import Boolean, Date, Float, Integer, List, String, Text

domain = Domain()


# --8<-- [start:genre_enum]
class Genre(Enum):
    FICTION = "FICTION"
    NON_FICTION = "NON_FICTION"
    SCIENCE = "SCIENCE"
    HISTORY = "HISTORY"
    BIOGRAPHY = "BIOGRAPHY"
    FANTASY = "FANTASY"
    MYSTERY = "MYSTERY"


# --8<-- [end:genre_enum]


# --8<-- [start:aggregate]
@domain.aggregate
class Book:
    title: String(max_length=200, required=True)
    author: String(max_length=150, required=True)
    isbn: String(max_length=13)
    price: Float()
    description: Text()
    publication_date: Date()
    page_count: Integer()
    in_print: Boolean(default=True)
    genre: String(max_length=20, choices=Genre)
    tags: List(content_type=String)


# --8<-- [end:aggregate]


domain.init(traverse=False)


# --8<-- [start:usage]
if __name__ == "__main__":
    with domain.domain_context():
        repo = domain.repository_for(Book)

        # Create several books
        gatsby = Book(
            title="The Great Gatsby",
            author="F. Scott Fitzgerald",
            isbn="9780743273565",
            price=12.99,
            description="A story of the mysteriously wealthy Jay Gatsby.",
            page_count=180,
            genre=Genre.FICTION.value,
            tags=["classic", "american", "jazz-age"],
        )
        repo.add(gatsby)

        brave_new = Book(
            title="Brave New World",
            author="Aldous Huxley",
            isbn="9780060850524",
            price=14.99,
            description="A dystopian novel set in a futuristic World State.",
            page_count=311,
            genre=Genre.FICTION.value,
            tags=["classic", "dystopia", "science-fiction"],
        )
        repo.add(brave_new)

        sapiens = Book(
            title="Sapiens",
            author="Yuval Noah Harari",
            isbn="9780062316097",
            price=18.99,
            description="A brief history of humankind.",
            page_count=443,
            genre=Genre.HISTORY.value,
            tags=["history", "anthropology", "non-fiction"],
        )
        repo.add(sapiens)

        # Retrieve by ID
        book = repo.get(gatsby.id)
        print(f"Retrieved: {book.title} by {book.author}")
        print(f"Genre: {book.genre}, Pages: {book.page_count}")
        print(f"Tags: {book.tags}")

        # Query all books
        all_books = repo._dao.query.all()
        print(f"\nTotal books: {all_books.total}")

        # Filter by genre
        fiction_books = repo._dao.query.filter(genre="FICTION").all()
        print(f"Fiction books: {fiction_books.total}")
        for b in fiction_books.items:
            print(f"  - {b.title}")

        # Order by title
        ordered = repo._dao.query.order_by("title").all()
        print("\nBooks alphabetically:")
        for b in ordered.items:
            print(f"  - {b.title} (${b.price})")

        # Verify
        assert all_books.total == 3
        assert fiction_books.total == 2
        print("\nAll checks passed!")
# --8<-- [end:usage]
