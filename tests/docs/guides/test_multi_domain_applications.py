"""The examples on the multi-domain applications guide behave as the page says."""

import pytest
from fastapi.testclient import TestClient

from protean.domain.context import has_domain_context
from protean.exceptions import ConfigurationError
from protean.integrations.pytest import DomainFixture
from protean.utils import DomainObjects
from protean.utils.globals import current_domain
from tests.docs.support import load_example

pytestmark = pytest.mark.no_test_domain

AGGREGATE = (DomainObjects.AGGREGATE,)


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


def test_the_cross_domain_test_on_the_page_passes(example):
    fixture = DomainFixture(example.fulfillment_domain)
    fixture.setup()
    try:
        example.test_customer_registration_creates_recipient(fixture)
    finally:
        fixture.teardown()


def test_the_api_tests_on_the_page_pass(example):
    client = TestClient(example.app)

    example.test_customer_endpoint_uses_identity_domain(client)
    example.test_product_endpoint_uses_catalogue_domain(client)
