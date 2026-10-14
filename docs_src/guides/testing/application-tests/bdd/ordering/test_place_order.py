# --8<-- [start:steps]
# tests/bdd/ordering/test_place_order.py
from myapp import domain
from myapp.commands import PlaceOrder
from myapp.models import Book, Customer, Inventory, Money, Order, OrderItemVO
from pytest_bdd import given, parsers, scenarios, then, when

scenarios("features/place_order.feature")


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


@given(
    parsers.parse('a customer "{name}"'),
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
def place_order(customer, book, name, qty, title):
    domain.process(
        PlaceOrder(
            customer_id=customer.id,
            items=[OrderItemVO(book_id=book.id, quantity=qty)],
            total=book.price.amount * qty,
        )
    )
    orders = domain.repository_for(Order).query.all()
    return orders.items[0]


@then("the order should be confirmed")
def order_confirmed(order):
    assert order.status == "CONFIRMED"


@then(parsers.parse('"{title}" should have {expected:d} copies in stock'))
def check_stock(title, expected):
    inventories = domain.repository_for(Inventory).query.all()
    inv = next(i for i in inventories.items if i.title == title)
    assert inv.quantity == expected


# --8<-- [end:steps]


# --8<-- [start:expected_failure]
from protean.exceptions import ValidationError


@when(
    parsers.parse('"{name}" tries to order {qty:d} copies of "{title}"'),
    target_fixture="order_result",
)
def try_place_order(customer, book, name, qty, title):
    try:
        domain.process(
            PlaceOrder(
                customer_id=customer.id,
                items=[OrderItemVO(book_id=book.id, quantity=qty)],
                total=book.price.amount * qty,
            )
        )
        return {"success": True}
    except ValidationError as exc:
        return {"success": False, "error": str(exc.messages)}


@then(parsers.parse('the order should be rejected with "{message}"'))
def order_rejected(order_result, message):
    assert order_result["success"] is False
    assert message in order_result["error"]


# --8<-- [end:expected_failure]


# --8<-- [start:outline_steps]
@given(
    parsers.parse('"{name}" adds {quantity:d} copies of a book priced at {price:f}'),
    target_fixture="cart",
)
def add_to_cart(customer, name, quantity, price):
    book = Book(title="Test Book", author="Author", price=Money(amount=price))
    domain.repository_for(Book).add(book)
    domain.repository_for(Inventory).add(
        Inventory(book_id=book.id, title=book.title, quantity=quantity)
    )
    return {"book": book, "quantity": quantity}


@when(
    parsers.parse('"{name}" places the order'),
    target_fixture="order",
)
def place_order_from_cart(customer, cart, name):
    domain.process(
        PlaceOrder(
            customer_id=customer.id,
            items=[OrderItemVO(book_id=cart["book"].id, quantity=cart["quantity"])],
            total=cart["book"].price.amount * cart["quantity"],
        )
    )
    orders = domain.repository_for(Order).query.all()
    return orders.items[0]


@then(parsers.parse("the order total should be {expected:f}"))
def check_total(order, expected):
    assert float(order.total) == expected


# --8<-- [end:outline_steps]


@then(parsers.parse('"{name}" should have {count:d} order in their history'))
def check_history(customer, name, count):
    customer = domain.repository_for(Customer).get(customer.id)
    assert len(customer.order_history) == count
