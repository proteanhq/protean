# --8<-- [start:steps]
# tests/integration/test_persistence.py
from myapp import domain
from myapp.models import Book, Money
from pytest_bdd import given, parsers, scenarios, then, when

scenarios("features/persistence.feature")


@given(
    parsers.parse('a book "{title}" by "{author}" at {price:f}'),
    target_fixture="book",
)
def new_book(title, author, price):
    return Book(title=title, author=author, price=Money(amount=price))


@given("the book is persisted")
def persist_book(book):
    domain.repository_for(Book).add(book)


@when(parsers.parse("the book price is updated to {price:f}"))
def update_price(book, price):
    book.price = Money(amount=price)


@when("the book is persisted and reloaded", target_fixture="reloaded")
def persist_and_reload(book):
    domain.repository_for(Book).add(book)
    return domain.repository_for(Book).get(book.id)


@then(parsers.parse('the reloaded book should have title "{title}"'))
def check_title(reloaded, title):
    assert reloaded.title == title


@then(parsers.parse("the reloaded book should have price {price:f}"))
def check_price(reloaded, price):
    assert reloaded.price.amount == price


# --8<-- [end:steps]
