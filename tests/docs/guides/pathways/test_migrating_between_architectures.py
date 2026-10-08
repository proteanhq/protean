"""The examples on the migrating between architectures guide behave as the page says."""

import pytest
from fastapi.testclient import TestClient

from protean.integrations.fastapi import DomainContextMiddleware
from tests.docs.support import load_example

pytestmark = pytest.mark.no_test_domain

ITEMS = [{"product_id": "book-1", "quantity": 2}, {"product_id": "pen-7"}]


def test_ddd_service_places_the_order_with_its_items():
    example = load_example("guides/pathways/migrating-between-architectures/001.py")
    example.domain.init(traverse=False)

    with example.domain.domain_context():
        order = example.OrderService().place_order(
            customer_id="cust-1", items=ITEMS, total=30.0
        )
        saved = example.domain.repository_for(example.Order).get(order.id)

    assert saved.customer_id == "cust-1"
    assert saved.total == 30.0
    assert sorted((i.product_id, i.quantity) for i in saved.items) == [
        ("book-1", 2),
        ("pen-7", 1),
    ]


def test_ddd_endpoint_returns_the_new_order_id():
    example = load_example("guides/pathways/migrating-between-architectures/001.py")
    example.domain.init(traverse=False)
    example.app.add_middleware(
        DomainContextMiddleware, route_domain_map={"/": example.domain}
    )

    response = TestClient(example.app).post(
        "/orders", json={"customer_id": "cust-1", "items": ITEMS, "total": 30.0}
    )

    assert response.status_code == 200
    with example.domain.domain_context():
        saved = example.domain.repository_for(example.Order).get(response.json()["id"])
    assert saved.customer_id == "cust-1"


def test_cqrs_command_handler_places_the_order():
    example = load_example("guides/pathways/migrating-between-architectures/002.py")
    example.domain.init(traverse=False)

    with example.domain.domain_context():
        example.domain.process(
            example.PlaceOrder(customer_id="cust-2", items=ITEMS, total=30.0)
        )
        saved = example.domain.repository_for(example.Order).find_by(
            customer_id="cust-2"
        )

    assert saved.total == 30.0
    assert sorted(i.product_id for i in saved.items) == ["book-1", "pen-7"]


def test_cqrs_endpoint_accepts_the_command():
    example = load_example("guides/pathways/migrating-between-architectures/002.py")
    example.domain.init(traverse=False)
    example.app.add_middleware(
        DomainContextMiddleware, route_domain_map={"/": example.domain}
    )

    response = TestClient(example.app).post(
        "/orders", json={"customer_id": "cust-3", "items": ITEMS, "total": 12.5}
    )

    assert response.status_code == 201
    assert response.json() == {"status": "accepted"}
    with example.domain.domain_context():
        saved = example.domain.repository_for(example.Order).find_by(
            customer_id="cust-3"
        )
    assert saved.total == 12.5


def test_projector_builds_the_order_summary_from_order_placed():
    example = load_example("guides/pathways/migrating-between-architectures/002.py")
    example.domain.init(traverse=False)

    with example.domain.domain_context():
        order = example.Order(customer_id="cust-4", total=30.0)
        for item in ITEMS:
            order.add_item(**item)
        order.place()
        example.domain.repository_for(example.Order).add(order)

        summary = example.domain.repository_for(example.OrderSummary).get(order.id)

    assert summary.customer_id == "cust-4"
    assert summary.total == 30.0
    assert summary.status == "placed"
    assert summary.item_count == 2


def test_marking_the_order_event_sourced_is_the_only_change():
    before = load_example("guides/pathways/migrating-between-architectures/003.py")
    after = load_example("guides/pathways/migrating-between-architectures/004.py")
    before.domain.init(traverse=False)
    after.domain.init(traverse=False)

    assert before.Order.meta_.is_event_sourced is False
    assert after.Order.meta_.is_event_sourced is True


def test_event_sourced_order_rebuilds_its_state_from_its_events():
    example = load_example("guides/pathways/migrating-between-architectures/005.py")
    example.domain.init(traverse=False)

    with example.domain.domain_context():
        order = example.Order.place(
            order_id="order-1", customer_id="cust-5", total=42.0
        )
        rebuilt = example.Order.from_events(order._events)

    assert rebuilt.id == "order-1"
    assert rebuilt.customer_id == "cust-5"
    assert rebuilt.total == 42.0
    assert rebuilt.status == "placed"


def test_command_handler_appends_events_and_the_repository_replays_them():
    example = load_example("guides/pathways/migrating-between-architectures/005.py")
    example.domain.init(traverse=False)

    with example.domain.domain_context():
        example.domain.process(
            example.PlaceOrder(order_id="order-2", customer_id="cust-6", total=18.0)
        )
        loaded = example.domain.repository_for(example.Order).get("order-2")

    assert loaded.id == "order-2"
    assert loaded.customer_id == "cust-6"
    assert loaded.total == 18.0
    assert loaded.status == "placed"


def test_account_is_event_sourced_and_customer_profile_is_not():
    example = load_example("guides/pathways/migrating-between-architectures/006.py")
    example.domain.init(traverse=False)

    assert example.Account.meta_.is_event_sourced is True
    assert example.CustomerProfile.meta_.is_event_sourced is False
