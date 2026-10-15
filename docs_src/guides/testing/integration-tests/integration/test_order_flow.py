import os

# --8<-- [start:steps]
# tests/integration/test_order_flow.py
from myapp import domain
from myapp.commands import AddBook, PlaceOrder
from myapp.models import BookCatalog, Customer, Inventory, Order
from pytest_bdd import given, parsers, scenarios, then, when

scenarios("features/order_flow.feature")


@given(
    parsers.parse('a book "{title}" is added to the catalog at {price:f}'),
    target_fixture="book_id",
)
def add_book(title, price):
    return domain.process(
        AddBook(title=title, author="Test Author", price_amount=price)
    )


@given(
    parsers.parse("the book has {quantity:d} copies in stock"),
)
def stock_book(book_id, quantity):
    inventory = Inventory(book_id=book_id, title="", quantity=quantity)
    domain.repository_for(Inventory).add(inventory)


@given(
    parsers.parse('a customer "{name}" exists'),
    target_fixture="customer",
)
def existing_customer(name):
    customer = Customer(name=name)
    domain.repository_for(Customer).add(customer)
    return customer


@when(
    parsers.parse('"{name}" places an order for {qty:d} copies of "{title}"'),
    target_fixture="order",
)
def place_order(customer, book_id, name, qty, title):
    domain.process(
        PlaceOrder(
            customer_id=customer.id,
            items=[{"book_id": book_id, "quantity": qty}],
        )
    )
    orders = domain.repository_for(Order).query.all()
    return orders.items[0]


@then(
    parsers.parse(
        'the catalog projection should show {sold:d} copies sold for "{title}"'
    )
)
def check_projection(book_id, sold, title):
    catalog = domain.repository_for(BookCatalog).get(book_id)
    assert catalog.copies_sold == sold


@then(parsers.parse('the order status should be "{status}"'))
def check_status(order, status):
    assert domain.repository_for(Order).get(order.id).status == status


@then(parsers.parse('"{title}" should have {expected:d} copies in stock'))
def check_stock(book_id, title, expected):
    inventory = domain.repository_for(Inventory).find_by_book(book_id)
    assert inventory.quantity == expected


@then(parsers.parse('"{name}" should have {count:d} order in their history'))
def check_history(customer, name, count):
    customer = domain.repository_for(Customer).get(customer.id)
    assert len(customer.order_history) == count


# --8<-- [end:steps]


def test_the_provider_follows_test_db():
    provider = domain.providers["default"].conn_info["provider"]
    assert provider == os.environ.get("TEST_DB", "memory")
