# --8<-- [start:full]
import pytest
from bookshelf.models import Money, Order, OrderItem

from protean.exceptions import ValidationError


def test_order_must_have_items():
    with pytest.raises(ValidationError) as exc:
        Order(customer_name="Alice")
    assert "at least one item" in str(exc.value.messages)


def test_cannot_modify_shipped_order():
    order = Order(
        customer_name="Alice",
        items=[
            OrderItem(book_title="Gatsby", quantity=1, unit_price=Money(amount=12.99))
        ],
    )
    order.ship()

    with pytest.raises(ValidationError) as exc:
        order.add_item("Another Book", 1, Money(amount=9.99))
    assert "shipped" in str(exc.value.messages)


# --8<-- [end:full]
