"""Run the examples on ``docs/patterns/message-tracing.md``."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from protean import Engine
from tests.docs.support import load_example

pytestmark = pytest.mark.no_test_domain

ITEMS = [{"sku": "BOOK-1", "qty": 2}]


@pytest.fixture
def example():
    module = load_example("patterns/message-tracing/001.py")
    with module.domain.domain_context():
        yield module


@pytest.fixture
def client(example):
    app = FastAPI()
    app.include_router(example.router)
    return TestClient(app)


def _order_messages(example, order_id):
    return example.domain.event_store.store.read(f"myapp::order-{order_id}")


def _place_through_api(client, correlation_id):
    response = client.post(
        "/orders",
        json={"customer_id": "cust-1", "items": ITEMS},
        headers={"X-Correlation-ID": correlation_id},
    )
    assert response.status_code == 201
    return response.json()["order_id"]


def test_endpoint_passes_the_callers_correlation_id_to_the_events(example, client):
    order_id = _place_through_api(client, "req-abc-123")

    messages = _order_messages(example, order_id)
    assert [m.metadata.headers.type for m in messages] == ["MyApp.OrderPlaced.v1"]
    assert messages[0].metadata.domain.correlation_id == "req-abc-123"


def test_endpoint_generates_a_correlation_id_when_the_header_is_missing(
    example, client
):
    response = client.post("/orders", json={"customer_id": "cust-1", "items": ITEMS})

    assert response.status_code == 201
    generated = response.json()["correlation_id"]
    assert len(generated) == 32
    (placed,) = _order_messages(example, response.json()["order_id"])
    assert placed.metadata.domain.correlation_id == generated


def test_causation_api_walks_up_down_and_builds_the_tree(example, client):
    order_id = _place_through_api(client, "req-abc-123")
    Engine(example.domain, test_mode=True).run()
    placed = _order_messages(example, order_id)[0]

    chain, _, _ = example.explain(placed, placed, "req-abc-123")
    assert [m.metadata.headers.type for m in chain] == [
        "MyApp.PlaceOrder.v1",
        "MyApp.OrderPlaced.v1",
    ]
    place_order = chain[0]
    assert placed.metadata.domain.causation_id == place_order.metadata.headers.id

    _, effects, root = example.explain(placed, place_order, "req-abc-123")
    assert [m.metadata.headers.type for m in effects] == [
        "MyApp.OrderPlaced.v1",
        "MyApp.ReserveInventory.v1",
        "MyApp.InventoryReserved.v1",
    ]
    assert all(m.metadata.domain.correlation_id == "req-abc-123" for m in effects)
    assert root.message_type == "MyApp.PlaceOrder.v1"
    (placed_node,) = root.children
    assert placed_node.message_type == "MyApp.OrderPlaced.v1"
    assert [c.message_type for c in placed_node.children] == [
        "MyApp.ReserveInventory.v1"
    ]


def test_subscriber_forwards_the_source_correlation_id(example, client):
    order_id = _place_through_api(client, "req-abc-123")
    example.domain.brokers["default"].publish(
        "payments",
        {
            "data": {"order_id": order_id},
            "metadata": {"domain": {"correlation_id": "pay-777"}},
        },
    )

    Engine(example.domain, test_mode=True).run()

    confirmed = [
        m
        for m in _order_messages(example, order_id)
        if m.metadata.headers.type == "MyApp.PaymentConfirmed.v1"
    ]
    assert len(confirmed) == 1
    assert confirmed[0].metadata.domain.correlation_id == "pay-777"


def test_dsl_records_a_generated_correlation_id_and_the_commands_id(example):
    result = example.place_order_with_generated_ids()

    (event,) = result.events
    store = example.domain.event_store.store
    (command,) = [
        m
        for m in store.trace_causation(event._metadata.headers.id)
        if m.metadata.headers.type == "MyApp.PlaceOrder.v1"
    ]
    assert event._metadata.domain.causation_id == command.metadata.headers.id
    assert command.metadata.domain.correlation_id == (
        event._metadata.domain.correlation_id
    )


def test_dsl_forwarded_correlation_id_groups_both_commands(example):
    first = example.place_order_with_generated_ids()
    corr_id = first.events[0]._metadata.domain.correlation_id

    result = example.reserve_in_the_same_operation(first)

    assert result.events.types == [example.InventoryReserved]
    assert result.aggregate.status == "RESERVED"
    assert [e._metadata.domain.correlation_id for e in result.all_events] == [
        corr_id,
        corr_id,
    ]
