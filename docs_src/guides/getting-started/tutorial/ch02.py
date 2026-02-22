from enum import Enum

from protean import Domain
from protean.fields import (
    Boolean,
    Date,
    Float,
    Integer,
    List,
    String,
    Text,
    ValueObject,
)

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


# --8<-- [start:money_vo]
@domain.value_object
class Money:
    currency: String(max_length=3, default="USD")
    amount: Float(required=True)


# --8<-- [end:money_vo]


# --8<-- [start:address_vo]
@domain.value_object
class Address:
    street: String(max_length=200, required=True)
    city: String(max_length=100, required=True)
    state: String(max_length=50)
    zip_code: String(max_length=20, required=True)
    country: String(max_length=50, default="US")


# --8<-- [end:address_vo]


# --8<-- [start:aggregate]
@domain.aggregate
class Book:
    title: String(max_length=200, required=True)
    author: String(max_length=150, required=True)
    isbn: String(max_length=13)
    price = ValueObject(Money)
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

        # Create a book with rich fields and a Money value object
        gatsby = Book(
            title="The Great Gatsby",
            author="F. Scott Fitzgerald",
            isbn="9780743273565",
            price=Money(amount=12.99),
            description="A story of the mysteriously wealthy Jay Gatsby.",
            page_count=180,
            genre=Genre.FICTION.value,
            tags=["classic", "american", "jazz-age"],
        )
        repo.add(gatsby)

        print(f"Book: {gatsby.title}")
        print(f"Price: ${gatsby.price.amount} {gatsby.price.currency}")
        print(f"Genre: {gatsby.genre}, Pages: {gatsby.page_count}")
        print(f"Tags: {gatsby.tags}")

        # Value objects are equal by value, not identity
        price1 = Money(amount=12.99, currency="USD")
        price2 = Money(amount=12.99, currency="USD")
        price3 = Money(amount=14.99, currency="USD")

        print(f"\nMoney(12.99, USD) == Money(12.99, USD)? {price1 == price2}")
        print(f"Money(12.99, USD) == Money(14.99, USD)? {price1 == price3}")

        # Create an Address value object
        shipping = Address(
            street="123 Main St",
            city="Springfield",
            state="IL",
            zip_code="62704",
        )
        print(f"\nAddress: {shipping.street}, {shipping.city}, {shipping.state}")
        print(f"Country (default): {shipping.country}")

        # Retrieve and verify persistence
        saved = repo.get(gatsby.id)
        print(
            f"\nRetrieved: {saved.title}, ${saved.price.amount} {saved.price.currency}"
        )

        # Verify
        assert saved.price.amount == 12.99
        assert saved.price.currency == "USD"
        assert price1 == price2
        assert price1 != price3
        assert shipping.country == "US"
        print("\nAll checks passed!")
# --8<-- [end:usage]
