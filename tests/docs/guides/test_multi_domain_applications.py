"""The examples on the multi-domain applications guide behave as the page says."""

import pytest
from fastapi.testclient import TestClient

from protean.domain.context import has_domain_context
from protean.exceptions import ConfigurationError
from protean.utils import DomainObjects
from protean.utils.globals import current_domain
from tests.docs.support import load_example

pytestmark = pytest.mark.no_test_domain

AGGREGATE = (DomainObjects.AGGREGATE,)

# Pytest finds fixtures by module attribute, so binding the page's own fixtures
# here makes the page's test functions run against them.
_page = load_example("guides/multi-domain-applications/001.py")
identity_fixture = _page.identity_fixture
fulfillment_fixture = _page.fulfillment_fixture


@pytest.fixture
def example():
    module = load_example("guides/multi-domain-applications/001.py")
    for domain in (
        module.identity_domain,
        module.catalogue_domain,
        module.fulfillment_domain,
    ):
        domain.init(traverse=False)
    return module


def test_each_domain_has_its_own_name(example):
    assert example.identity_domain.name == "Identity"
    assert example.catalogue_domain.name == "Catalogue"
    assert example.fulfillment_domain.name == "Fulfillment"


def test_each_domain_resolves_its_own_aggregate(example):
    with example.identity_domain.domain_context():
        assert (
            current_domain.fetch_element_cls_from_registry("Customer", AGGREGATE)
            is example.Customer
        )

    with example.fulfillment_domain.domain_context():
        assert (
            current_domain.fetch_element_cls_from_registry("Recipient", AGGREGATE)
            is example.Recipient
        )


def test_a_domain_does_not_find_another_domains_aggregate(example):
    with (
        example.fulfillment_domain.domain_context(),
        pytest.raises(ConfigurationError),
    ):
        current_domain.fetch_element_cls_from_registry("Customer", AGGREGATE)

    with (
        example.identity_domain.domain_context(),
        pytest.raises(ConfigurationError),
    ):
        current_domain.fetch_element_cls_from_registry("Recipient", AGGREGATE)

    with (
        example.catalogue_domain.domain_context(),
        pytest.raises(ConfigurationError),
    ):
        current_domain.fetch_element_cls_from_registry("Customer", AGGREGATE)


def test_the_middleware_activates_the_domain_for_each_url_prefix(example):
    def active_domain() -> dict:
        if not has_domain_context():
            return {"domain": None}
        return {"domain": current_domain.name}

    for path in ("/customers", "/products", "/shipments", "/health"):
        example.app.get(path)(active_domain)

    client = TestClient(example.app)

    assert client.get("/customers").json() == {"domain": "Identity"}
    assert client.get("/products").json() == {"domain": "Catalogue"}
    assert client.get("/shipments").json() == {"domain": "Fulfillment"}
    assert client.get("/health").json() == {"domain": None}


def test_external_events_carry_the_shared_type_string(example):
    assert example.PaymentReceived.__type__ == "Billing.PaymentReceived.v1"
    assert example.StockReserved.__type__ == "Inventory.StockReserved.v1"
    assert example.StockUnavailable.__type__ == "Inventory.StockUnavailable.v1"


def test_the_sync_handler_stores_a_local_recipient_with_the_correlation_id(example):
    with example.fulfillment_domain.domain_context():
        event = example.CustomerRegistered(customer_id="cust-1", name="Alice")
        example.CustomerSyncHandler().on_registered(event)

        recipient = current_domain.repository_for(example.Recipient).find_by(
            customer_id="cust-1"
        )

    assert recipient.name == "Alice"
    assert recipient.delivery_address is None


def test_fact_events_add_a_fact_event_for_customer():
    example = load_example("guides/multi-domain-applications/002.py")
    example.identity_domain.init(traverse=False)

    assert example.Customer.meta_.fact_events is True
    assert [
        name.rsplit(".", 1)[-1] for name in example.identity_domain.registry.events
    ] == ["CustomerFactEvent"]


def test_the_page_fixtures_set_up_each_domain_in_sync_mode(
    identity_fixture, fulfillment_fixture
):
    assert identity_fixture.domain is _page.identity_domain
    assert fulfillment_fixture.domain is _page.fulfillment_domain
    for fixture in (identity_fixture, fulfillment_fixture):
        assert fixture.domain.config["command_processing"] == "sync"
        assert fixture.domain.config["event_processing"] == "sync"


def test_the_cross_domain_test_on_the_page_passes(fulfillment_fixture):
    _page.test_customer_registration_creates_recipient(fulfillment_fixture)


def test_the_api_tests_on_the_page_pass(example):
    client = TestClient(example.app)

    example.test_customer_endpoint_uses_identity_domain(client)
    example.test_product_endpoint_uses_catalogue_domain(client)


def test_the_lifespan_initializes_every_domain_before_serving(example):
    with TestClient(example.app) as client:
        response = client.post("/customers", json={"name": "Alice"})

    assert response.json() == {"domain": "Identity"}


def test_the_subscriber_translates_the_payload_into_a_stored_recipient(example):
    example.fulfillment_domain.config["command_processing"] = "sync"

    with example.fulfillment_domain.domain_context():
        example.CustomerEventSubscriber()(
            {
                "type": "CustomerRegistered",
                "customer_id": "cust-9",
                "full_name": "Ada Lovelace",
                "shipping_address": "12 St James's Square",
            }
        )
        recipient = current_domain.repository_for(example.Recipient).find_by(
            customer_id="cust-9"
        )

    assert recipient.name == "Ada Lovelace"
    assert recipient.delivery_address == "12 St James's Square"


def test_the_subscriber_ignores_other_payload_types(example):
    example.fulfillment_domain.config["command_processing"] = "sync"

    with example.fulfillment_domain.domain_context():
        example.CustomerEventSubscriber()(
            {"type": "CustomerDeleted", "customer_id": "cust-9"}
        )
        stored = current_domain.repository_for(example.Recipient).query.all()

    assert stored.total == 0


def _pm_state(example, order_id):
    stream = f"{example.OrderFulfillmentPM.meta_.stream_category}-{order_id}"
    transitions = example.fulfillment_domain.event_store.store.read(stream)
    assert transitions
    return transitions[-1].to_domain_object()


def test_the_process_manager_completes_after_payment_and_stock(example):
    pm = example.OrderFulfillmentPM
    with example.fulfillment_domain.domain_context():
        pm._handle(example.OrderPlaced(order_id="ord-1"))
        pm._handle(example.PaymentReceived(payment_id="pay-1", order_id="ord-1"))
        pm._handle(example.StockReserved(order_id="ord-1", inventory_item_id="inv-1"))
        # A completed process ignores later events.
        pm._handle(
            example.StockUnavailable(order_id="ord-1", inventory_item_id="inv-1")
        )
        final = _pm_state(example, "ord-1")

    assert final.state["status"] == "completed"
    assert final.is_complete is True


def test_the_process_manager_ends_when_stock_is_unavailable(example):
    pm = example.OrderFulfillmentPM
    with example.fulfillment_domain.domain_context():
        pm._handle(example.OrderPlaced(order_id="ord-2"))
        pm._handle(
            example.StockUnavailable(order_id="ord-2", inventory_item_id="inv-1")
        )
        # The process has ended, so a late payment does not move it on.
        pm._handle(example.PaymentReceived(payment_id="pay-2", order_id="ord-2"))
        final = _pm_state(example, "ord-2")

    assert final.state["status"] == "stock_unavailable"
    assert final.is_complete is True


def test_the_process_manager_waits_for_payment_before_stock(example):
    pm = example.OrderFulfillmentPM
    with example.fulfillment_domain.domain_context():
        pm._handle(example.OrderPlaced(order_id="ord-3"))
        pm._handle(example.StockReserved(order_id="ord-3", inventory_item_id="inv-1"))
        final = _pm_state(example, "ord-3")

    assert final.state["status"] == "awaiting_payment"
    assert final.is_complete is False
