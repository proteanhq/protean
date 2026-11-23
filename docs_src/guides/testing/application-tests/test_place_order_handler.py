# --8<-- [start:handler_tests]
# tests/test_place_order_handler.py
import pytest
from myapp import domain
from myapp.commands import PlaceOrder
from myapp.models import Book, Customer, Inventory, Money, Order, OrderItemVO

from protean.exceptions import ValidationError


@pytest.fixture
def customer():
    customer = Customer(name="Alice")
    domain.repository_for(Customer).add(customer)
    return customer


def stock_book(title, price, quantity):
    book = Book(title=title, author="Test Author", price=Money(amount=price))
    domain.repository_for(Book).add(book)
    domain.repository_for(Inventory).add(
        Inventory(book_id=book.id, title=title, quantity=quantity)
    )
    return book


def test_the_command_does_not_accept_a_total(customer):
    book = stock_book("Dune", 15.50, 5)

    with pytest.raises(ValidationError) as exc:
        PlaceOrder(
            customer_id=customer.id,
            items=[OrderItemVO(book_id=book.id, quantity=1)],
            total=1.0,
        )

    assert exc.value.messages == {"total": ["Extra inputs are not permitted"]}


def test_the_order_total_is_the_sum_of_the_book_prices(customer):
    dune = stock_book("Dune", 15.50, 5)
    emma = stock_book("Emma", 4.25, 5)

    domain.process(
        PlaceOrder(
            customer_id=customer.id,
            items=[
                OrderItemVO(book_id=dune.id, quantity=2),
                OrderItemVO(book_id=emma.id, quantity=3),
            ],
        )
    )

    orders = domain.repository_for(Order).query.all().items
    assert len(orders) == 1
    assert orders[0].total == 43.75


def test_an_unknown_book_is_rejected(customer):
    with pytest.raises(ValidationError) as exc:
        domain.process(
            PlaceOrder(
                customer_id=customer.id,
                items=[OrderItemVO(book_id="no-such-book", quantity=1)],
            )
        )

    assert exc.value.messages == {"items": ["Unknown book: no-such-book"]}
    assert domain.repository_for(Order).query.all().items == []


def test_a_quantity_above_the_stock_is_rejected(customer):
    book = stock_book("Dune", 15.50, 1)

    with pytest.raises(ValidationError) as exc:
        domain.process(
            PlaceOrder(
                customer_id=customer.id,
                items=[OrderItemVO(book_id=book.id, quantity=2)],
            )
        )

    assert exc.value.messages == {"items": ["Insufficient stock"]}
    assert domain.repository_for(Order).query.all().items == []


# --8<-- [end:handler_tests]
