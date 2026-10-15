import pytest
from bookstore import (
    Book,
    BookPublished,
    Inventory,
    Money,
    Order,
    OrderFulfillmentService,
    OrderItem,
)

from protean.exceptions import ValidationError


# --8<-- [start:state_transition]
def test_publish_changes_status():
    book = Book(
        title="Dune",
        author="Frank Herbert",
        body="A lengthy description...",
    )
    book.publish()

    assert book.status == "PUBLISHED"


# --8<-- [end:state_transition]


# --8<-- [start:event_raising]
def test_publish_raises_event():
    book = Book(
        title="Dune",
        author="Frank Herbert",
        body="A lengthy description...",
    )
    book.publish()

    assert len(book._events) == 1
    assert isinstance(book._events[0], BookPublished)
    assert book._events[0].book_id == book.id


# --8<-- [end:event_raising]


# --8<-- [start:entity]
def test_cancel_item_recalculates_order_total():
    order = Order(
        customer_name="Alice",
        total_amount=30.0,
        items=[
            OrderItem(product_id="prod-1", quantity=2, price=10.0, subtotal=20.0),
            OrderItem(product_id="prod-2", quantity=1, price=10.0, subtotal=10.0),
        ],
    )
    order.cancel_item("prod-2")

    assert len(order.items) == 1
    assert order.total_amount == 20.0


# --8<-- [end:entity]


# --8<-- [start:value_object]
def test_money_addition():
    m1 = Money(amount=12.99, currency="USD")
    m2 = Money(amount=7.01, currency="USD")

    total = m1.add(m2)

    assert total.amount == 20.00
    assert total.currency == "USD"


def test_money_rejects_different_currencies():
    usd = Money(amount=10.0, currency="USD")
    eur = Money(amount=10.0, currency="EUR")

    with pytest.raises(ValidationError) as exc:
        usd.add(eur)
    assert "Cannot add different currencies" in str(exc.value.messages)


# --8<-- [end:value_object]


# --8<-- [start:invalid_state]
def test_order_total_must_match_items():
    with pytest.raises(ValidationError) as exc:
        Order(
            customer_name="Alice",
            total_amount=100.0,  # Does not match items
            items=[
                OrderItem(product_id="1", quantity=2, price=10.0, subtotal=20.0),
            ],
        )
    assert "Total should be sum of item prices" in str(exc.value.messages)


# --8<-- [end:invalid_state]


def test_an_order_without_items_must_have_a_zero_total():
    with pytest.raises(ValidationError) as exc:
        Order(customer_name="Alice", total_amount=100.0, items=[])
    assert "Total should be sum of item prices" in str(exc.value.messages)


# --8<-- [start:valid_state]
def test_order_with_matching_total_is_valid():
    order = Order(
        customer_name="Alice",
        total_amount=20.0,
        items=[
            OrderItem(product_id="1", quantity=2, price=10.0, subtotal=20.0),
        ],
    )
    assert order is not None
    assert order.total_amount == 20.0


# --8<-- [end:valid_state]


# --8<-- [start:pre_invariant]
def test_cannot_modify_shipped_order():
    order = Order(customer_name="Alice", status="SHIPPED")

    with pytest.raises(ValidationError) as exc:
        order.add_item("prod-3", 1, 9.99)
    assert "shipped" in str(exc.value.messages)


# --8<-- [end:pre_invariant]


# --8<-- [start:domain_service]
def test_order_fulfillment():
    order = Order(
        customer_name="Alice",
        total_amount=20.0,
        items=[OrderItem(product_id="dune", quantity=2, price=10.0, subtotal=20.0)],
    )
    inventory = Inventory(product_id="dune", title="Dune", quantity=10)

    service = OrderFulfillmentService(order, [inventory])
    service.confirm_order()

    assert order.status == "CONFIRMED"
    assert inventory.quantity == 10  # the service checks stock; it does not reserve


# --8<-- [end:domain_service]


# --8<-- [start:domain_service_invariant]
def test_fulfillment_rejects_out_of_stock():
    order = Order(
        customer_name="Alice",
        total_amount=200.0,
        items=[OrderItem(product_id="dune", quantity=20, price=10.0, subtotal=200.0)],
    )
    inventory = Inventory(product_id="dune", title="Dune", quantity=5)

    service = OrderFulfillmentService(order, [inventory])
    with pytest.raises(ValidationError) as exc:
        service.confirm_order()
    assert "Insufficient stock" in str(exc.value.messages)
    assert order.status == "PENDING"


# --8<-- [end:domain_service_invariant]
