# --8<-- [start:domain]
from protean import Domain, atomic_change, invariant
from protean.exceptions import ValidationError
from protean.fields import Float, HasMany, Identifier, Integer, String, Text

domain = Domain(name="Bookstore")


@domain.event(part_of="Book")
class BookPublished:
    book_id: Identifier(required=True)


@domain.aggregate
class Book:
    title: String(max_length=200, required=True)
    author: String(max_length=100, required=True)
    body: Text()
    status: String(max_length=20, default="DRAFT")

    def publish(self):
        self.status = "PUBLISHED"
        self.raise_(BookPublished(book_id=self.id))


@domain.value_object
class Money:
    amount: Float(required=True)
    currency: String(max_length=3, default="USD")

    def add(self, other):
        if other.currency != self.currency:
            raise ValidationError({"currency": ["Cannot add different currencies"]})
        return Money(
            amount=round(self.amount + other.amount, 2), currency=self.currency
        )


@domain.entity(part_of="Order")
class OrderItem:
    product_id: String(max_length=50, required=True)
    quantity: Integer(min_value=1, required=True)
    price: Float(default=0.0)
    subtotal: Float(default=0.0)


@domain.aggregate
class Order:
    customer_name: String(max_length=100, required=True)
    total_amount: Float(default=0.0)
    status: String(max_length=20, default="PENDING")
    items = HasMany(OrderItem)

    @invariant.post
    def total_should_be_sum_of_item_prices(self):
        if self.items and self.total_amount != sum(i.subtotal for i in self.items):
            raise ValidationError({"_entity": ["Total should be sum of item prices"]})

    @invariant.pre
    def shipped_orders_cannot_change(self):
        if self.status == "SHIPPED":
            raise ValidationError({"_entity": ["A shipped order cannot be changed"]})

    def add_item(self, product_id, quantity, price):
        with atomic_change(self):
            self.add_items(
                OrderItem(
                    product_id=product_id,
                    quantity=quantity,
                    price=price,
                    subtotal=quantity * price,
                )
            )
            self.total_amount = sum(i.subtotal for i in self.items)

    def cancel_item(self, product_id):
        item = next(i for i in self.items if i.product_id == product_id)
        with atomic_change(self):
            self.remove_items(item)
            self.total_amount = sum(i.subtotal for i in self.items)


@domain.aggregate
class Inventory:
    product_id: String(max_length=50, required=True)
    title: String(max_length=200, required=True)
    quantity: Integer(default=0)


@domain.domain_service(part_of=[Order, Inventory])
class OrderFulfillmentService:
    def __init__(self, order, inventories):
        super().__init__(order, *inventories)
        self.order = order
        self.inventories = {inv.product_id: inv for inv in inventories}

    @invariant.pre
    def every_item_should_be_in_stock(self):
        for item in self.order.items:
            stock = self.inventories.get(item.product_id)
            if stock is None or stock.quantity < item.quantity:
                raise ValidationError(
                    {"_service": [f"Insufficient stock for {item.product_id}"]}
                )

    def confirm_order(self):
        self.order.status = "CONFIRMED"


# --8<-- [end:domain]


# --8<-- [start:conftest]
import pytest

from protean.integrations.pytest import DomainFixture


@pytest.fixture(scope="session")
def app_fixture():
    domain.config["event_processing"] = "sync"
    domain.config["command_processing"] = "sync"

    fixture = DomainFixture(domain)
    fixture.setup()
    yield fixture
    fixture.teardown()


@pytest.fixture(autouse=True)
def _ctx(app_fixture):
    with app_fixture.domain_context():
        yield


# --8<-- [end:conftest]


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
