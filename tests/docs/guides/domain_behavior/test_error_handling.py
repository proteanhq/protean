"""The examples on the error handling guide behave as the page says."""

import pytest
from fastapi.testclient import TestClient

from protean.exceptions import (
    InvalidOperationError,
    InvalidStateError,
    ObjectNotFoundError,
    ValidationError,
)
from tests.docs.support import load_example

pytestmark = pytest.mark.no_test_domain

NO_ITEMS = {"_entity": ["Order must contain at least one item"]}


@pytest.fixture
def invariant_example():
    example = load_example("guides/domain-behavior/error-handling/001.py")
    example.domain.init(traverse=False)
    with example.domain.domain_context():
        yield example


@pytest.fixture
def cancel_example():
    example = load_example("guides/domain-behavior/error-handling/002.py")
    example.domain.init(traverse=False)
    with example.domain.domain_context():
        yield example


@pytest.fixture
def app_example():
    example = load_example("guides/domain-behavior/error-handling/003.py")
    example.domain.init(traverse=False)
    return example


def test_an_order_without_items_fails_the_invariant(invariant_example):
    with pytest.raises(ValidationError) as exc:
        invariant_example.Order(customer_id="c1", items=[])

    assert exc.value.messages == NO_ITEMS


def test_an_order_with_an_item_is_valid(invariant_example):
    order = invariant_example.Order(
        customer_id="c1", items=[invariant_example.OrderItem(product_id="p1")]
    )

    assert order.status == "draft"


def test_cancelling_a_shipped_order_raises_invalid_state(cancel_example):
    order = cancel_example.Order(status="shipped")

    with pytest.raises(InvalidStateError) as exc:
        order.cancel()

    assert str(exc.value) == "Cannot cancel a shipped order"
    assert order.status == "shipped"


def test_cancelling_a_draft_order_succeeds(cancel_example):
    order = cancel_example.Order()

    order.cancel()

    assert order.status == "cancelled"


def test_the_service_places_and_stores_the_order(app_example):
    with app_example.domain.domain_context():
        order_id = app_example.OrderService().place_order(
            "c1", [app_example.OrderItem(product_id="p1")]
        )

        assert app_example.load_order(order_id).status == "placed"


def test_the_service_lets_the_validation_error_through(app_example):
    with app_example.domain.domain_context():
        with pytest.raises(ValidationError) as exc:
            app_example.OrderService().place_order("c1", [])

    assert exc.value.messages == NO_ITEMS


def test_loading_a_missing_order_raises_not_found(app_example):
    with app_example.domain.domain_context():
        with pytest.raises(ObjectNotFoundError):
            app_example.load_order("missing")


def test_registering_an_email_twice_is_rejected(app_example):
    with app_example.domain.domain_context():
        app_example.register_customer("jane@example.com")

        with pytest.raises(InvalidOperationError) as exc:
            app_example.register_customer("jane@example.com")

    assert str(exc.value) == "Email already registered"


def test_a_valid_request_is_accepted(app_example):
    client = TestClient(app_example.app)

    response = client.post(
        "/orders", json={"customer_id": "c1", "items": [{"product_id": "p1"}]}
    )

    assert response.status_code == 201
    assert response.json() == {"status": "accepted"}


def test_an_order_without_items_maps_to_400_with_a_correlation_id(app_example):
    client = TestClient(app_example.app)

    response = client.post("/orders", json={"customer_id": "c1", "items": []})

    assert response.status_code == 400
    body = response.json()
    assert body["error"] == NO_ITEMS
    assert body["correlation_id"] == response.headers["X-Correlation-ID"]


def test_a_missing_field_maps_to_400(app_example):
    client = TestClient(app_example.app)

    response = client.post("/orders", json={"items": [{"product_id": "p1"}]})

    assert response.status_code == 400
    assert response.json()["error"] == {"customer_id": ["is required"]}


def test_the_page_test_passes(app_example):
    with app_example.domain.domain_context():
        app_example.test_order_requires_items()
