"""Run the examples on ``docs/patterns/consuming-events-from-other-domains.md``."""

import logging
from datetime import UTC, datetime

import pytest

from tests.docs.support import load_example

pytestmark = pytest.mark.no_test_domain

ORDER_PLACED = {
    "type": "OrderPlaced",
    "order_id": "ord-1",
    "customer_id": "cust-1",
    "items": [
        {"product_id": "prod-1", "quantity": 2, "sku_name": "Mug"},
    ],
}


@pytest.fixture
def run():
    """Load an example, publish payloads to its broker, and return it."""
    contexts = []

    def _run(example, stream, *payloads, setup=None):
        example.domain.init(traverse=False)
        context = example.domain.domain_context()
        context.push()
        contexts.append(context)
        if setup:
            setup(example)
        for payload in payloads:
            example.domain.brokers["default"].publish(stream, payload)
        return example

    yield _run
    for context in reversed(contexts):
        context.pop()


def _shipments(example):
    return example.domain.repository_for(example.Shipment)._dao.query.all().items


def _commands(example):
    return [
        message.metadata.headers.type
        for message in example.domain.event_store.store.read("$all")
        if message.metadata.domain.kind == "COMMAND"
    ]


def test_the_subscriber_translates_order_placed_into_create_shipment(run):
    example = run(
        load_example("patterns/consuming-events-from-other-domains/001.py"),
        "orders",
        ORDER_PLACED,
    )

    shipments = _shipments(example)
    assert len(shipments) == 1
    assert shipments[0].order_id == "ord-1"
    assert shipments[0].customer_id == "cust-1"
    assert shipments[0].items == [{"product_id": "prod-1", "quantity": 2}]
    assert shipments[0].shipping_priority == "standard"
    assert _commands(example) == ["Fulfillment.CreateShipment.v1"]


def test_the_subscriber_ignores_other_event_types(run):
    example = run(
        load_example("patterns/consuming-events-from-other-domains/001.py"),
        "orders",
        {**ORDER_PLACED, "type": "OrderCancelled"},
    )

    assert _shipments(example) == []


def test_the_payment_subscriber_maps_external_names_to_internal_ones(run):
    def add_order(example):
        example.domain.repository_for(example.Order).add(
            example.Order(order_id="ord-9")
        )

    example = run(
        load_example("patterns/consuming-events-from-other-domains/002.py"),
        "payments",
        {
            "type": "PaymentConfirmed",
            "reference_id": "ord-9",
            "transaction_id": "txn-1",
            "amount": 42.0,
            "currency_code": "EUR",
            "confirmed_at": "2025-01-01T10:00:00+00:00",
        },
        setup=add_order,
    )

    order = example.domain.repository_for(example.Order).get("ord-9")
    assert order.status == "PAID"
    assert order.payment_id == "txn-1"
    assert order.amount == 42.0
    assert order.currency == "EUR"
    assert order.paid_at == datetime(2025, 1, 1, 10, 0, tzinfo=UTC)


def test_the_payment_subscriber_ignores_other_event_types(run):
    def add_order(example):
        example.domain.repository_for(example.Order).add(
            example.Order(order_id="ord-9")
        )

    example = run(
        load_example("patterns/consuming-events-from-other-domains/002.py"),
        "payments",
        {
            "type": "PaymentFailed",
            "reference_id": "ord-9",
            "transaction_id": "txn-1",
            "amount": 42.0,
            "currency_code": "EUR",
            "confirmed_at": "2025-01-01T10:00:00+00:00",
        },
        setup=add_order,
    )

    order = example.domain.repository_for(example.Order).get("ord-9")
    assert (order.status, order.payment_id) == ("PENDING", None)


def test_stock_depleted_raises_product_became_unavailable(run):
    def add_product(example):
        example.domain.repository_for(example.Product).add(
            example.Product(product_id="sku-1", name="Mug")
        )

    example = run(
        load_example("patterns/consuming-events-from-other-domains/003.py"),
        "inventory-external",
        {"type": "StockDepleted", "sku": "sku-1"},
        setup=add_product,
    )

    messages = example.domain.event_store.store.read("catalogue::product-sku-1")
    assert [m.metadata.headers.type for m in messages] == [
        "Catalogue.ProductBecameUnavailable.v1"
    ]
    assert messages[0].data["reason"] == "external_stock_depleted"


def test_other_inventory_events_raise_nothing(run):
    def add_product(example):
        example.domain.repository_for(example.Product).add(
            example.Product(product_id="sku-1", name="Mug")
        )

    example = run(
        load_example("patterns/consuming-events-from-other-domains/003.py"),
        "inventory-external",
        {"type": "StockReplenished", "sku": "sku-1"},
        setup=add_product,
    )

    assert example.domain.event_store.store.read("catalogue::product-sku-1") == []


def test_the_filter_keeps_only_physical_items(run):
    payload = {
        **ORDER_PLACED,
        "items": [
            {"product_id": "prod-1", "type": "physical"},
            {"product_id": "ebook-1", "type": "digital"},
        ],
    }
    example = run(
        load_example("patterns/consuming-events-from-other-domains/004.py"),
        "orders",
        payload,
    )

    shipments = _shipments(example)
    assert len(shipments) == 1
    assert shipments[0].items == [{"product_id": "prod-1", "type": "physical"}]


@pytest.mark.parametrize(
    "payload",
    [
        {**ORDER_PLACED, "type": "OrderShipped"},
        {**ORDER_PLACED, "items": [{"product_id": "ebook-1", "type": "digital"}]},
    ],
    ids=["other-event-type", "digital-only"],
)
def test_the_filter_creates_no_shipment(run, payload):
    example = run(
        load_example("patterns/consuming-events-from-other-domains/004.py"),
        "orders",
        payload,
    )

    assert _shipments(example) == []


def test_the_subscriber_enriches_the_shipment_from_the_customer_profile(run):
    def add_profile(example):
        example.domain.repository_for(example.CustomerProfile).add(
            example.CustomerProfile(
                customer_id="cust-1",
                default_shipping_address="1 Main St",
                shipping_tier="express",
            )
        )

    example = run(
        load_example("patterns/consuming-events-from-other-domains/005.py"),
        "orders",
        ORDER_PLACED,
        setup=add_profile,
    )

    shipments = _shipments(example)
    assert len(shipments) == 1
    assert shipments[0].shipping_address == "1 Main St"
    assert shipments[0].shipping_priority == "express"


def test_the_enriching_subscriber_ignores_other_event_types(run):
    def add_profile(example):
        example.domain.repository_for(example.CustomerProfile).add(
            example.CustomerProfile(customer_id="cust-1")
        )

    example = run(
        load_example("patterns/consuming-events-from-other-domains/005.py"),
        "orders",
        {**ORDER_PLACED, "type": "OrderCancelled"},
        setup=add_profile,
    )

    assert _shipments(example) == []


@pytest.mark.parametrize("field", ["items", "line_items"])
def test_the_subscriber_reads_items_under_either_name(run, field):
    payload = {
        "type": "OrderPlaced",
        "order_id": "ord-1",
        field: [{"product_id": "prod-1"}],
    }
    example = run(
        load_example("patterns/consuming-events-from-other-domains/006.py"),
        "orders",
        payload,
    )

    shipments = _shipments(example)
    assert len(shipments) == 1
    assert shipments[0].items == [{"product_id": "prod-1"}]


def test_the_versioned_subscriber_ignores_other_event_types(run):
    example = run(
        load_example("patterns/consuming-events-from-other-domains/006.py"),
        "orders",
        {**ORDER_PLACED, "type": "OrderCancelled"},
    )

    assert _shipments(example) == []


def test_a_valid_payload_creates_a_shipment(run):
    example = run(
        load_example("patterns/consuming-events-from-other-domains/007.py"),
        "orders",
        ORDER_PLACED,
    )

    assert [s.order_id for s in _shipments(example)] == ["ord-1"]


def test_the_validating_subscriber_ignores_other_event_types(run):
    example = run(
        load_example("patterns/consuming-events-from-other-domains/007.py"),
        "orders",
        {**ORDER_PLACED, "type": "OrderCancelled"},
    )

    assert _shipments(example) == []


@pytest.mark.parametrize(
    "payload, level, message",
    [
        (
            {"type": "OrderPlaced", "items": [{"product_id": "prod-1"}]},
            logging.WARNING,
            "Received OrderPlaced without order_id, skipping",
        ),
        (
            {"type": "OrderPlaced", "order_id": "ord-1", "items": []},
            logging.WARNING,
            "Received OrderPlaced with no items for ord-1",
        ),
        (
            {"type": "OrderPlaced", "order_id": "ord-1", "items": [{"id": 1}]},
            logging.ERROR,
            "Failed to process OrderPlaced ord-1:",
        ),
        (
            {
                "type": "OrderPlaced",
                "order_id": "ord-1",
                "customer_id": "cust-1",
                "items": "not-a-list",
            },
            logging.ERROR,
            "Failed to process OrderPlaced ord-1:",
        ),
    ],
    ids=["no-order-id", "no-items", "no-customer-id", "items-not-a-list"],
)
def test_a_bad_payload_is_logged_and_skipped(run, caplog, payload, level, message):
    with caplog.at_level(logging.WARNING):
        example = run(
            load_example("patterns/consuming-events-from-other-domains/007.py"),
            "orders",
            payload,
        )

    records = [r for r in caplog.records if r.name.endswith("_007")]
    assert len(records) == 1
    assert records[0].levelno == level
    assert records[0].getMessage().startswith(message)
    assert _shipments(example) == []
