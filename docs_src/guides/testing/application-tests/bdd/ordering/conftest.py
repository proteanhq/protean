# --8<-- [start:ordering_steps]
# tests/bdd/ordering/conftest.py
from myapp import domain
from myapp.models import Book, Customer, Inventory, Money
from pytest_bdd import given, parsers


@given(
    parsers.parse('a customer "{name}"'),
    target_fixture="customer",
)
def existing_customer(name):
    customer = Customer(name=name)
    domain.repository_for(Customer).add(customer)
    return customer


@given(
    parsers.parse('a book "{title}" with {stock:d} copies in stock'),
    target_fixture="book",
)
def book_in_stock(title, stock):
    book = Book(title=title, author="Test Author", price=Money(amount=15.99))
    domain.repository_for(Book).add(book)
    inventory = Inventory(book_id=book.id, title=title, quantity=stock)
    domain.repository_for(Inventory).add(inventory)
    return book


# --8<-- [end:ordering_steps]
