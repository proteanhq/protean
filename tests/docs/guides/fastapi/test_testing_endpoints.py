"""The examples on the endpoint tests guide behave as the page says."""

from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient

from tests.docs.support import load_example

pytestmark = [pytest.mark.no_test_domain, pytest.mark.fastapi]


@contextmanager
def run_fixture(fixture, *args):
    """Run a generator fixture from the example: set up, yield its value, tear down."""
    steps = fixture.__wrapped__(*args)
    value = next(steps)
    try:
        yield value
    finally:
        with pytest.raises(StopIteration):
            next(steps)


@contextmanager
def bookstore():
    """Load the bookstore example and enter its conftest fixtures."""
    example = load_example("guides/fastapi/testing-endpoints/001.py")
    with run_fixture(example.app_fixture) as app_fixture:
        with run_fixture(example._ctx, app_fixture):
            yield example, example.client.__wrapped__()


def test_the_conftest_recipe_makes_processing_sync_and_cleans_up_after_each_test():
    example = load_example("guides/fastapi/testing-endpoints/001.py")
    Customer = example.Customer

    with run_fixture(example.app_fixture) as app_fixture:
        assert example.domain.config["command_processing"] == "sync"
        assert example.domain.config["event_processing"] == "sync"

        with run_fixture(example._ctx, app_fixture):
            example.domain.repository_for(Customer).add(Customer(name="Alice"))
            assert len(example.domain.repository_for(Customer).query.all().items) == 1

        with run_fixture(example._ctx, app_fixture):
            assert example.domain.repository_for(Customer).query.all().items == []


def test_place_order_returns_201_and_stores_a_pending_order():
    with bookstore() as (example, client):
        example.test_place_order_returns_201(client)
        example.test_place_order_creates_order(client)

        orders = example.domain.repository_for(example.Order).query.all().items
        assert len(orders) == 2
        assert {order.status for order in orders} == {"PENDING"}


def test_a_missing_customer_is_404_and_an_empty_customer_id_is_400():
    with bookstore() as (example, client):
        example.test_place_order_for_nonexistent_customer_returns_404(client)
        example.test_place_order_with_invalid_data_returns_400(client)

        # Neither request stored an order.
        assert example.domain.repository_for(example.Order).query.all().items == []


def test_the_query_endpoint_returns_the_customer_or_404():
    with bookstore() as (example, client):
        example.test_get_customer_returns_200(client)
        example.test_get_nonexistent_customer_returns_404(client)


def test_the_order_placed_handler_takes_the_books_out_of_stock_before_the_response():
    with bookstore() as (example, client):
        example.test_placing_order_updates_inventory(client)


def test_the_alice_fixture_seeds_a_customer_an_order_can_reference():
    with bookstore() as (example, client):
        alice = example.alice.__wrapped__()

        example.test_place_order(client, alice)

        stored = example.domain.repository_for(example.Customer).get(alice.id)
        assert stored.email == "alice@example.com"


def test_the_auth_client_sends_the_bearer_token():
    with bookstore() as (example, client):
        auth_client = example.auth_client.__wrapped__(client)

        assert auth_client.headers["Authorization"] == "Bearer test-token-for-alice"


def test_the_error_helper_checks_the_status_and_the_message():
    with bookstore() as (example, client):
        response = client.get("/customers/does-not-exist")

        example.assert_error_response(response, 404, "does-not-exist")
        with pytest.raises(AssertionError):
            example.assert_error_response(response, 400)
        with pytest.raises(AssertionError):
            example.assert_error_response(response, 404, "some other message")


def test_each_path_prefix_runs_in_its_own_domain():
    example = load_example("guides/fastapi/testing-endpoints/002.py")
    with (
        run_fixture(example.identity_fixture) as identity,
        run_fixture(example.ordering_fixture) as ordering,
        run_fixture(example._ctx, identity, ordering),
    ):
        assert example.identity_domain.config["command_processing"] == "sync"
        assert example.ordering_domain.config["command_processing"] == "sync"
        client = TestClient(example.app)

        customer = client.post("/customers", json={"name": "Alice"}).json()
        order = client.post("/orders", json={"customer_name": "Alice"}).json()

        assert customer["domain"] == "Identity"
        assert order["domain"] == "Ordering"
        with example.ordering_domain.domain_context():
            stored = example.ordering_domain.repository_for(example.Order)
            assert stored.get(order["id"]).customer_name == "Alice"
