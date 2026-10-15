# --8<-- [start:full]
from bookshelf.commands import AddBook
from bookshelf.models import Money, Order, OrderItem

from protean.utils.globals import current_domain


def test_full_order_flow():
    """End-to-end: add book -> place order -> verify."""
    current_domain.process(
        AddBook(title="Dune", author="Frank Herbert", price_amount=15.99),
        asynchronous=False,
    )

    order = Order(
        customer_name="Alice",
        items=[
            OrderItem(book_title="Dune", quantity=2, unit_price=Money(amount=15.99))
        ],
    )
    current_domain.repository_for(Order).add(order)

    order.confirm()
    current_domain.repository_for(Order).add(order)

    saved = current_domain.repository_for(Order).get(order.id)
    assert saved.status == "CONFIRMED"


# --8<-- [end:full]
