"""Run the examples on ``docs/patterns/factory-methods-for-aggregate-creation.md``."""

import re
import subprocess
import sys
from datetime import UTC, datetime

import pytest

from protean.exceptions import ValidationError
from tests.docs.support import DOCS_SRC, REPO_ROOT, load_example

pytestmark = pytest.mark.no_test_domain

CART_ITEMS = [
    {"product_id": "p1", "name": "Widget", "quantity": 2, "unit_price": 10.0},
    {"product_id": "p2", "name": "Gadget", "quantity": 1, "unit_price": 25.0},
]
ADDRESS = {
    "street": "123 Main St",
    "city": "Springfield",
    "state": "IL",
    "postal_code": "62701",
    "country": "US",
}


@pytest.fixture
def orders():
    example = load_example("patterns/factory-methods-for-aggregate-creation/001.py")
    example.domain.init(traverse=False)
    with example.domain.domain_context():
        yield example


@pytest.fixture
def payments():
    example = load_example("patterns/factory-methods-for-aggregate-creation/002.py")
    example.domain.init(traverse=False)
    with example.domain.domain_context():
        yield example


def item_rows(order):
    return [
        (item.product_id, item.name, item.quantity, item.unit_price)
        for item in order.items
    ]


def delivered_order(orders, status="delivered"):
    order = orders.Order(
        customer_id="cust-1",
        shipping_address=orders.Address(**ADDRESS),
        status=status,
    )
    order.add_item(product_id="p1", name="Widget", quantity=2, unit_price=10.0)
    order.add_item(product_id="p2", name="Gadget", quantity=1, unit_price=25.0)
    return order


def all_orders(orders):
    return orders.domain.repository_for(orders.Order).query.all().items


# --- Order defaults and from_cart ---------------------------------------------


def test_a_new_order_starts_as_a_draft_with_zero_total(orders):
    order = orders.Order(customer_id="cust-1")

    assert order.status == "draft"
    assert order.total == 0.0
    assert order.is_renewal is False
    assert order._events == []


def test_from_cart_builds_a_placed_order_and_raises_order_placed(orders):
    address = orders.Address(**ADDRESS)

    order = orders.Order.from_cart(
        customer_id="cust-1", cart_items=CART_ITEMS, shipping_address=address
    )

    assert order.customer_id == "cust-1"
    assert order.shipping_address == address
    assert item_rows(order) == [
        ("p1", "Widget", 2, 10.0),
        ("p2", "Gadget", 1, 25.0),
    ]
    assert order.total == 45.0
    assert order.status == "placed"
    assert order.is_renewal is False

    assert len(order._events) == 1
    event = order._events[0]
    assert isinstance(event, orders.OrderPlaced)
    assert event.order_id == order.order_id
    assert event.customer_id == "cust-1"
    assert event.total == 45.0


def test_from_cart_rejects_an_empty_cart(orders):
    with pytest.raises(ValidationError) as exc:
        orders.Order.from_cart(
            customer_id="cust-1",
            cart_items=[],
            shipping_address=orders.Address(**ADDRESS),
        )

    assert exc.value.messages == {"items": ["Order must have at least one item"]}


# --- from_subscription_renewal ------------------------------------------------


def test_renewal_copies_the_previous_order_at_current_prices(orders):
    previous = delivered_order(orders)

    renewed = orders.Order.from_subscription_renewal(
        previous_order=previous, current_prices={"p1": 12.0, "p2": 30.0}
    )

    assert renewed.order_id != previous.order_id
    assert renewed.customer_id == "cust-1"
    assert renewed.shipping_address == previous.shipping_address
    assert item_rows(renewed) == [
        ("p1", "Widget", 2, 12.0),
        ("p2", "Gadget", 1, 30.0),
    ]
    assert renewed.total == 54.0
    assert renewed.is_renewal is True
    assert renewed.status == "placed"

    assert len(renewed._events) == 1
    event = renewed._events[0]
    assert isinstance(event, orders.OrderPlaced)
    assert (event.order_id, event.customer_id, event.total) == (
        renewed.order_id,
        "cust-1",
        54.0,
    )
    # The previous order is read, never changed
    assert previous.status == "delivered"
    assert previous.total == 45.0


@pytest.mark.parametrize("status", ["draft", "placed", "cancelled"])
def test_renewal_rejects_an_order_that_was_not_delivered(orders, status):
    previous = delivered_order(orders, status=status)

    with pytest.raises(ValidationError) as exc:
        orders.Order.from_subscription_renewal(
            previous_order=previous, current_prices={"p1": 12.0, "p2": 30.0}
        )

    assert exc.value.messages == {
        "previous_order": ["Can only renew from a delivered order"]
    }
    assert previous.status == status


def test_renewal_of_an_order_without_items_is_rejected(orders):
    previous = orders.Order(customer_id="cust-1", status="delivered")

    with pytest.raises(ValidationError) as exc:
        orders.Order.from_subscription_renewal(
            previous_order=previous, current_prices={}
        )

    assert exc.value.messages == {"items": ["Order must have at least one item"]}


# --- as_replacement -----------------------------------------------------------


def test_replacement_holds_only_the_returned_items_at_original_price(orders):
    original = delivered_order(orders)

    replacement = orders.Order.as_replacement(
        original_order=original, returned_item_ids=["p2"]
    )

    assert replacement.customer_id == "cust-1"
    assert replacement.shipping_address == original.shipping_address
    assert item_rows(replacement) == [("p2", "Gadget", 1, 25.0)]
    assert replacement.total == 25.0
    assert replacement.status == "placed"
    assert replacement.is_renewal is False
    assert [type(e) for e in replacement._events] == [orders.OrderPlaced]
    assert replacement._events[0].total == 25.0


def test_replacement_with_no_matching_items_is_rejected(orders):
    original = delivered_order(orders)

    with pytest.raises(ValidationError) as exc:
        orders.Order.as_replacement(original_order=original, returned_item_ids=["p9"])

    assert exc.value.messages == {"items": ["Order must have at least one item"]}


# --- Thin handlers ------------------------------------------------------------


def test_place_order_handler_saves_an_order_built_from_the_cart(orders):
    orders.domain.process(
        orders.PlaceOrder(
            customer_id="cust-1", items=CART_ITEMS, shipping_address=ADDRESS
        ),
        asynchronous=False,
    )

    [saved] = all_orders(orders)
    assert saved.customer_id == "cust-1"
    assert saved.shipping_address == orders.Address(**ADDRESS)
    assert item_rows(saved) == [("p1", "Widget", 2, 10.0), ("p2", "Gadget", 1, 25.0)]
    assert saved.total == 45.0
    assert saved.status == "placed"


def test_renew_handler_saves_a_renewal_of_a_saved_order(orders):
    repo = orders.domain.repository_for(orders.Order)
    previous = delivered_order(orders)
    repo.add(previous)

    orders.domain.process(
        orders.RenewSubscriptionOrder(
            previous_order_id=previous.order_id,
            current_prices={"p1": 12.0, "p2": 30.0},
        ),
        asynchronous=False,
    )

    [renewed] = [o for o in all_orders(orders) if o.order_id != previous.order_id]
    assert renewed.is_renewal is True
    assert renewed.total == 54.0
    assert renewed.status == "placed"


def test_renew_handler_rejects_an_undelivered_order(orders):
    repo = orders.domain.repository_for(orders.Order)
    previous = delivered_order(orders, status="placed")
    repo.add(previous)

    with pytest.raises(ValidationError) as exc:
        orders.domain.process(
            orders.RenewSubscriptionOrder(
                previous_order_id=previous.order_id, current_prices={"p1": 12.0}
            ),
            asynchronous=False,
        )

    assert exc.value.messages == {
        "previous_order": ["Can only renew from a delivered order"]
    }
    assert [o.order_id for o in all_orders(orders)] == [previous.order_id]


def test_replacement_handler_saves_a_replacement_order(orders):
    repo = orders.domain.repository_for(orders.Order)
    original = delivered_order(orders)
    repo.add(original)

    orders.domain.process(
        orders.CreateReplacementOrder(
            original_order_id=original.order_id, returned_item_ids=["p1"]
        ),
        asynchronous=False,
    )

    [replacement] = [o for o in all_orders(orders) if o.order_id != original.order_id]
    assert item_rows(replacement) == [("p1", "Widget", 2, 10.0)]
    assert replacement.total == 20.0
    assert replacement.is_renewal is False


# --- Standalone OrderFactory --------------------------------------------------


def saved_customer_and_cart(orders, suspended=False, lines=True):
    customer = orders.Customer(
        name="Ada",
        is_suspended=suspended,
        default_address=orders.Address(**ADDRESS),
    )
    cart = orders.Cart()
    if lines:
        cart.add_items(
            orders.CartLine(
                product_id="p1", product_name="Widget", quantity=3, unit_price=10.0
            )
        )
    orders.domain.repository_for(orders.Customer).add(customer)
    orders.domain.repository_for(orders.Cart).add(cart)
    return customer, cart


def test_order_factory_builds_an_order_from_saved_cart_and_customer(orders):
    customer, cart = saved_customer_and_cart(orders)

    order = orders.OrderFactory.from_cart_checkout(
        cart_id=cart.id, customer_id=customer.id
    )

    assert order.customer_id == customer.id
    assert order.shipping_address == orders.Address(**ADDRESS)
    assert item_rows(order) == [("p1", "Widget", 3, 10.0)]
    assert order.total == 30.0
    assert order.status == "placed"
    assert [type(e) for e in order._events] == [orders.OrderPlaced]
    assert order._events[0].total == 30.0


def test_order_factory_rejects_a_suspended_customer(orders):
    customer, cart = saved_customer_and_cart(orders, suspended=True)

    with pytest.raises(ValidationError) as exc:
        orders.OrderFactory.from_cart_checkout(cart_id=cart.id, customer_id=customer.id)

    assert exc.value.messages == {
        "customer": ["Suspended customers cannot place orders"]
    }


def test_order_factory_rejects_an_empty_cart(orders):
    customer, cart = saved_customer_and_cart(orders, lines=False)

    with pytest.raises(ValidationError) as exc:
        orders.OrderFactory.from_cart_checkout(cart_id=cart.id, customer_id=customer.id)

    assert exc.value.messages == {"cart": ["Cannot create order from empty cart"]}


# --- The page's own tests -----------------------------------------------------


def test_the_page_tests_pass_under_pytest():
    # Run the file the way a reader would: as a pytest module, with its own
    # test_domain fixture. A collection warning fails it.
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            str(DOCS_SRC / "patterns/factory-methods-for-aggregate-creation/001.py"),
            "-p",
            "no:cacheprovider",
            "-p",
            "no:randomly",
            "-q",
            "--import-mode=importlib",
            "-W",
            "error::pytest.PytestCollectionWarning",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert re.search(r"\b4 passed\b", result.stdout), result.stdout


# --- PaymentFactory (anti-corruption layer) -----------------------------------


def stripe_payload(status="succeeded", event_type="payment_intent.succeeded", **extra):
    obj = {
        "id": "pi_123",
        "amount": 4500,
        "currency": "usd",
        "status": status,
        "created": 1_700_000_000,
        **extra,
    }
    return {"type": event_type, "data": {"object": obj}}


@pytest.mark.parametrize(
    ("stripe_status", "status"),
    [
        ("succeeded", "completed"),
        ("requires_payment_method", "failed"),
        ("canceled", "cancelled"),
        ("processing", "pending"),
    ],
)
def test_payment_factory_maps_stripe_status(payments, stripe_status, status):
    payment = payments.PaymentFactory.from_stripe_webhook(
        stripe_payload(status=stripe_status, receipt_email="ada@example.com")
    )

    assert payment.status == status
    assert payment.external_id == "pi_123"
    assert payment.amount == payments.Money(cents=4500, currency="USD")
    assert payment.customer_email == "ada@example.com"
    assert payment.paid_at == datetime.fromtimestamp(1_700_000_000, tz=UTC)


def test_payment_factory_defaults_a_missing_receipt_email(payments):
    payment = payments.PaymentFactory.from_stripe_webhook(stripe_payload())

    assert payment.customer_email == ""


def test_subscriber_saves_a_payment_for_a_succeeded_webhook(payments):
    payments.domain.brokers.publish(stream="stripe-webhooks", message=stripe_payload())

    [saved] = payments.domain.repository_for(payments.Payment).query.all().items
    assert saved.external_id == "pi_123"
    assert saved.status == "completed"
    assert saved.amount == payments.Money(cents=4500, currency="USD")


def test_subscriber_ignores_other_webhook_types(payments):
    payments.domain.brokers.publish(
        stream="stripe-webhooks",
        message=stripe_payload(event_type="payment_intent.created"),
    )

    assert payments.domain.repository_for(payments.Payment).query.all().items == []
