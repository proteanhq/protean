"""Run the examples on ``docs/patterns/creating-identities-early.md``."""

import time
import uuid

import pytest
from fastapi.testclient import TestClient

from protean.exceptions import ValidationError
from tests.docs.support import load_example

pytestmark = pytest.mark.no_test_domain


def _is_uuid(value) -> bool:
    try:
        uuid.UUID(str(value))
    except ValueError:
        return False
    return True


@pytest.fixture
def orders():
    example = load_example("patterns/creating-identities-early/001.py")
    example.domain.init(traverse=False)
    with example.domain.domain_context():
        yield example


@pytest.fixture
def carts():
    example = load_example("patterns/creating-identities-early/002.py")
    example.domain.init(traverse=False)
    with example.domain.domain_context():
        yield example


@pytest.fixture
def measurements():
    example = load_example("patterns/creating-identities-early/003.py")
    example.domain.init(traverse=False)
    with example.domain.domain_context():
        yield example


@pytest.fixture
def books():
    example = load_example("patterns/creating-identities-early/004.py")
    example.domain.init(traverse=False)
    with example.domain.domain_context():
        yield example


@pytest.fixture
def invoices():
    example = load_example("patterns/creating-identities-early/005.py")
    example.domain.init(traverse=False)
    with example.domain.domain_context():
        yield example


def _all_orders(example):
    repo = example.domain.repository_for(example.Order)
    return repo.query.all().items


# --- An identity at construction -------------------------------------------


def test_auto_assigns_a_uuid_before_the_order_is_added(orders):
    order = orders.Order(customer_id="cust-789", total=149.99)
    assigned = order.order_id
    assert _is_uuid(assigned)

    repo = orders.domain.repository_for(orders.Order)
    repo.add(order)

    loaded = repo.get(assigned)
    assert loaded.order_id == assigned
    assert loaded.customer_id == "cust-789"
    assert loaded.total == 149.99


def test_two_orders_get_different_identities(orders):
    first = orders.Order(customer_id="cust-789", total=1.0)
    second = orders.Order(customer_id="cust-789", total=1.0)
    assert first.order_id != second.order_id


def test_the_example_order_keeps_the_identity_it_was_given():
    example = load_example("patterns/creating-identities-early/001.py")
    # The last section on the page binds ``order`` with a supplied identity.
    assert example.order.order_id == "ord-a1b2c3d4"


def test_default_id_field_is_added_and_generated_at_construction(carts):
    assert _is_uuid(carts.cart.id)

    cart = carts.Cart(customer_id="cust-1", total=10.0)
    assigned = cart.id
    assert _is_uuid(assigned)

    repo = carts.domain.repository_for(carts.Cart)
    repo.add(cart)
    loaded = repo.get(assigned)
    assert loaded.id == assigned
    assert loaded.customer_id == "cust-1"


# --- A caller-supplied identity ------------------------------------------


def test_a_supplied_identity_is_used_as_given_through_persistence(orders):
    order = orders.Order(order_id="ord-a1b2c3d4", customer_id="cust-789", total=149.99)
    assert order.order_id == "ord-a1b2c3d4"

    repo = orders.domain.repository_for(orders.Order)
    repo.add(order)

    loaded = repo.get("ord-a1b2c3d4")
    assert loaded.order_id == "ord-a1b2c3d4"
    assert loaded.total == 149.99


# --- An identity from a function -----------------------------------------


def test_function_strategy_assigns_an_epoch_integer_before_add(measurements):
    before = int(time.time() * 1000)
    measurement = measurements.Measurement(value=21.5)
    after = int(time.time() * 1000)

    # The function returns an int; Protean keeps identities as strings, so
    # the value is the epoch milliseconds in string form.
    assigned = measurement.measurement_id
    assert isinstance(assigned, str)
    assert before <= int(assigned) <= after

    repo = measurements.domain.repository_for(measurements.Measurement)
    repo.add(measurement)
    loaded = repo.get(assigned)
    assert loaded.measurement_id == assigned
    assert loaded.value == 21.5


# --- Identifier on commands ----------------------------------------------


def test_the_command_keeps_the_identity_the_caller_supplies(orders):
    command = orders.PlaceOrder(order_id="ord-1", customer_id="cust-1", total=5.0)
    assert command.order_id == "ord-1"


def test_the_command_generates_an_identity_when_the_caller_leaves_it_out(orders):
    command = orders.PlaceOrder(customer_id="cust-1", total=5.0)
    assert _is_uuid(command.order_id)


def test_the_handler_creates_the_order_with_the_command_identity(orders):
    orders.domain.process(
        orders.PlaceOrder(
            order_id="ord-a1b2c3d4", customer_id="cust-789", items=["sku-1"], total=9.5
        )
    )

    loaded = orders.domain.repository_for(orders.Order).get("ord-a1b2c3d4")
    assert loaded.order_id == "ord-a1b2c3d4"
    assert loaded.customer_id == "cust-789"
    assert loaded.total == 9.5


# --- Idempotent creation -------------------------------------------------


def test_a_retried_command_does_not_create_a_second_order(orders):
    orders.domain.process(
        orders.PlaceOrder(order_id="ord-retry", customer_id="cust-1", total=10.0)
    )
    # The retry carries the same identity. The handler finds the order and
    # does nothing, so the first write stands.
    orders.domain.process(
        orders.PlaceOrder(order_id="ord-retry", customer_id="cust-2", total=99.0)
    )

    stored = _all_orders(orders)
    assert [(o.order_id, o.customer_id, o.total) for o in stored] == [
        ("ord-retry", "cust-1", 10.0)
    ]


def test_a_command_without_an_identity_creates_an_order_each_time(orders):
    # The page's anti-pattern: no identity from the caller, so a redelivery
    # cannot be told apart from a first attempt.
    orders.domain.process(orders.PlaceOrder(customer_id="cust-1", total=10.0))
    orders.domain.process(orders.PlaceOrder(customer_id="cust-1", total=10.0))

    stored = _all_orders(orders)
    identities = {o.order_id for o in stored}
    assert len(identities) == 2
    assert all(_is_uuid(identity) for identity in identities)
    assert {o.customer_id for o in stored} == {"cust-1"}


# --- At the API boundary -------------------------------------------------


def test_the_api_returns_the_client_identity_and_stores_the_order(orders):
    client = TestClient(orders.app)

    response = client.post(
        "/orders",
        json={"order_id": "ord-client-1", "customer_id": "cust-5", "total": 20.0},
    )

    assert response.status_code == 200
    assert response.json() == {"order_id": "ord-client-1", "status": "accepted"}
    loaded = orders.domain.repository_for(orders.Order).get("ord-client-1")
    assert loaded.customer_id == "cust-5"
    assert loaded.total == 20.0


def test_the_api_generates_an_identity_when_the_client_sends_none(orders):
    client = TestClient(orders.app)

    response = client.post("/orders", json={"customer_id": "cust-6", "total": 30.0})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "accepted"
    assert _is_uuid(body["order_id"])
    loaded = orders.domain.repository_for(orders.Order).get(body["order_id"])
    assert loaded.order_id == body["order_id"]
    assert loaded.customer_id == "cust-6"


def test_a_retried_api_request_does_not_create_a_second_order(orders):
    client = TestClient(orders.app)
    payload = {"order_id": "ord-twice", "customer_id": "cust-7", "total": 40.0}

    client.post("/orders", json=payload)
    response = client.post("/orders", json=payload)

    assert response.json() == {"order_id": "ord-twice", "status": "accepted"}
    assert [o.order_id for o in _all_orders(orders)] == ["ord-twice"]


# --- A natural key -------------------------------------------------------


def test_the_natural_key_is_the_identity(books):
    book = books.Book(isbn="9780321125217", title="Domain-Driven Design")
    assert book.isbn == "9780321125217"

    repo = books.domain.repository_for(books.Book)
    repo.add(book)
    loaded = repo.get("9780321125217")
    assert loaded.title == "Domain-Driven Design"


def test_the_natural_key_is_not_generated(books):
    with pytest.raises(ValidationError) as exc:
        books.Book(title="Domain-Driven Design")
    assert exc.value.messages == {"isbn": ["is required"]}


# --- A database sequence -------------------------------------------------


def test_an_increment_identity_is_assigned_only_on_add(invoices):
    repo = invoices.domain.repository_for(invoices.Invoice)

    first = invoices.Invoice(customer_name="Ada")
    # Identity is handed back to the database: nothing before the write.
    assert first.invoice_number is None
    repo.add(first)
    assert first.invoice_number == 1

    second = invoices.Invoice(customer_name="Tim")
    repo.add(second)
    assert second.invoice_number == 2
    assert repo.get(2).customer_name == "Tim"
