"""Run the examples on ``docs/patterns/application-service-vs-command-handler.md``."""

import hashlib

import pytest
from fastapi.testclient import TestClient

from protean.exceptions import ValidationError
from tests.docs.support import load_example

pytestmark = pytest.mark.no_test_domain


def _messages(domain, stream):
    """Return ``(type name, data)`` for each message stored in ``stream``."""
    return [
        (m.metadata.headers.type.split(".")[-2], m.data)
        for m in domain.event_store.store.read(stream)
    ]


def _events_of(domain, aggregate_cls, identifier):
    stream = f"{aggregate_cls.meta_.stream_category}-{identifier}"
    return _messages(domain, stream)


# --- Application Service: User Registration ---


@pytest.fixture
def users():
    example = load_example("patterns/application-service-vs-command-handler/001.py")
    with example.domain.domain_context():
        yield example


def test_register_user_returns_the_registered_user(users):
    user = users.UserService().register_user(
        email="jane@example.com", name="Jane", password="s3cret"
    )

    assert isinstance(user, users.User)
    assert user.user_id is not None
    assert user.email == "jane@example.com"
    assert user.status == "active"
    salt, digest = user.password_hash.split(":")
    assert (
        digest
        == hashlib.scrypt(b"s3cret", salt=bytes.fromhex(salt), n=2**14, r=8, p=1).hex()
    )
    assert user.registered_at is not None


def test_registered_user_is_in_the_repository(users):
    user = users.UserService().register_user(
        email="jane@example.com", name="Jane", password="s3cret"
    )

    stored = users.domain.repository_for(users.User).get(user.user_id)
    assert stored.email == "jane@example.com"
    assert stored.name == "Jane"
    assert stored.status == "active"


def test_register_user_raises_user_registered(users):
    user = users.UserService().register_user(
        email="jane@example.com", name="Jane", password="s3cret"
    )

    assert _events_of(users.domain, users.User, user.user_id) == [
        (
            "UserRegistered",
            {"user_id": user.user_id, "email": "jane@example.com", "name": "Jane"},
        )
    ]


@pytest.mark.fastapi
def test_the_users_endpoint_registers_a_user():
    example = load_example("patterns/application-service-vs-command-handler/001.py")
    response = TestClient(example.app).post(
        "/users", json={"email": "jane@example.com", "name": "Jane", "password": "pw"}
    )

    assert response.status_code == 201
    body = response.json()
    assert (body["email"], body["name"], body["status"]) == (
        "jane@example.com",
        "Jane",
        "active",
    )
    with example.domain.domain_context():
        stored = example.domain.repository_for(example.User).get(body["id"])
        assert stored.email == "jane@example.com"


# --- Command Handler: Order Payment Processing ---


@pytest.fixture
def payments():
    # Loading the file runs the page's per-call example once.
    example = load_example("patterns/application-service-vs-command-handler/002.py")
    with example.domain.domain_context():
        yield example


def _pending_order(example, total=99.99, status="pending_payment"):
    order = example.Order(customer_id="cust-1", status=status, total=total)
    example.domain.repository_for(example.Order).add(order)
    return order


def _reload(example, order):
    return example.domain.repository_for(example.Order).get(order.order_id)


def test_per_call_override_processes_the_command_at_once(payments):
    assert payments.result is None
    order = _reload(payments, payments.order)
    assert order.status == "paid"
    assert order.payment_id == "pay-456"


def test_sync_command_processing_marks_the_order_paid(payments):
    payments.domain.config["command_processing"] = "sync"
    order = _pending_order(payments)

    payments.domain.process(
        payments.ConfirmPayment(
            order_id=order.order_id, payment_id="pay-789", amount=99.99
        )
    )

    paid = _reload(payments, order)
    assert paid.status == "paid"
    assert paid.payment_id == "pay-789"
    assert paid.paid_at is not None
    assert _events_of(payments.domain, payments.Order, order.order_id) == [
        (
            "OrderPaid",
            {
                "order_id": order.order_id,
                "customer_id": "cust-1",
                "payment_id": "pay-789",
                "amount": 99.99,
            },
        )
    ]


def test_async_processing_stores_the_command_and_returns(payments):
    order = _pending_order(payments)

    result = payments.domain.process(
        payments.ConfirmPayment(
            order_id=order.order_id, payment_id="pay-789", amount=99.99
        )
    )

    # The caller gets the command's position in the event store, not a result.
    assert isinstance(result, int)
    assert _reload(payments, order).status == "pending_payment"
    stream = f"{payments.Order.meta_.stream_category}:command"
    # The first command in the stream is the page's per-call example.
    assert _messages(payments.domain, stream)[1:] == [
        (
            "ConfirmPayment",
            {"order_id": order.order_id, "payment_id": "pay-789", "amount": 99.99},
        )
    ]


@pytest.mark.fastapi
def test_the_payment_webhook_accepts_the_command_and_returns(payments):
    order = _pending_order(payments)

    response = TestClient(payments.app).post(
        "/webhooks/payment",
        json={"order_id": order.order_id, "payment_id": "pay-789", "amount": 99.99},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "accepted"}
    # Processing is asynchronous, so the order waits for the server.
    assert _reload(payments, order).status == "pending_payment"
    stream = f"{payments.Order.meta_.stream_category}:command"
    assert _messages(payments.domain, stream)[1:] == [
        (
            "ConfirmPayment",
            {"order_id": order.order_id, "payment_id": "pay-789", "amount": 99.99},
        )
    ]


@pytest.mark.parametrize(
    ("status", "amount", "error"),
    [
        (
            "draft",
            99.99,
            {"status": ["Only orders pending payment can be confirmed"]},
        ),
        (
            "pending_payment",
            50.0,
            {"amount": ["Payment amount is less than order total"]},
        ),
    ],
    ids=["not_pending_payment", "amount_below_total"],
)
def test_confirm_payment_rejects_and_leaves_the_order_unchanged(
    payments, status, amount, error
):
    order = _pending_order(payments, status=status)

    with pytest.raises(ValidationError) as exc:
        payments.domain.process(
            payments.ConfirmPayment(
                order_id=order.order_id, payment_id="pay-789", amount=amount
            ),
            asynchronous=False,
        )

    assert exc.value.messages == error
    unchanged = _reload(payments, order)
    assert unchanged.status == status
    assert unchanged.payment_id is None
    assert unchanged.paid_at is None
    assert _events_of(payments.domain, payments.Order, order.order_id) == []


# --- Anti-patterns: the fixes ---


def test_product_service_returns_the_created_product():
    example = load_example("patterns/application-service-vs-command-handler/003.py")
    with example.domain.domain_context():
        product = example.ProductService().create_product(name="Lamp", price=24.5)

        assert product.product_id is not None
        stored = example.domain.repository_for(example.Product).get(product.product_id)
        assert (stored.name, stored.price) == ("Lamp", 24.5)


@pytest.mark.fastapi
def test_the_products_endpoint_returns_the_created_product():
    example = load_example("patterns/application-service-vs-command-handler/003.py")
    response = TestClient(example.app).post(
        "/products", json={"name": "Lamp", "price": 24.5}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Lamp"
    with example.domain.domain_context():
        stored = example.domain.repository_for(example.Product).get(body["id"])
        assert (stored.name, stored.price) == ("Lamp", 24.5)


def _place_order_and_reload_stock(example):
    domain = example.domain
    domain.config["event_processing"] = "sync"
    domain.config["command_processing"] = "sync"
    with domain.domain_context():
        domain.repository_for(example.Inventory).add(
            example.Inventory(product_id="prod-1", available=10)
        )
        order = example.Order()
        order.place("prod-1", 3)
        domain.repository_for(example.Order).add(order)
        return order, domain.repository_for(example.Inventory).get("prod-1")


def test_event_handler_reserves_stock_directly():
    example = load_example("patterns/application-service-vs-command-handler/004.py")
    _, inventory = _place_order_and_reload_stock(example)

    assert (inventory.available, inventory.reserved) == (7, 3)


def test_event_handler_reserves_stock_through_a_command():
    example = load_example("patterns/application-service-vs-command-handler/005.py")
    order, inventory = _place_order_and_reload_stock(example)

    assert (inventory.available, inventory.reserved) == (7, 3)
    with example.domain.domain_context():
        stream = f"{example.Inventory.meta_.stream_category}:command"
        assert _messages(example.domain, stream) == [
            (
                "ReserveInventory",
                {"product_id": "prod-1", "quantity": 3, "order_id": order.order_id},
            )
        ]
