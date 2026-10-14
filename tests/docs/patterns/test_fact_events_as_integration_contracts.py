"""Run the examples on ``docs/patterns/fact-events-as-integration-contracts.md``."""

import pytest

from protean.utils.reflection import declared_fields
from tests.docs.support import load_example

pytestmark = pytest.mark.no_test_domain


def _fields(cls):
    return set(declared_fields(cls)) - {"_metadata"}


@pytest.fixture
def customers():
    example = load_example("patterns/fact-events-as-integration-contracts/002.py")
    example.customers.init(traverse=False)
    with example.customers.domain_context():
        yield example


def _fact_messages(example, customer_id):
    return example.customers.event_store.store.read(
        f"customers::customer-fact-{customer_id}"
    )


def _fact_payloads(example, customer_id):
    return [m.data for m in _fact_messages(example, customer_id)]


def _fact_envelopes(example, customer_id):
    """The fact events in the shape the outbox publishes them to a broker."""
    return [m.to_external_dict() for m in _fact_messages(example, customer_id)]


def _save_customer(example, **values):
    customer = example.Customer(
        first_name="Ada", last_name="Lovelace", email="ada@example.com", **values
    )
    example.customers.repository_for(example.Customer).add(customer)
    return customer


def test_each_granular_event_carries_only_what_changed():
    example = load_example("patterns/fact-events-as-integration-contracts/001.py")

    assert _fields(example.CustomerPhoneUpdated) == {"customer_id", "new_phone"}
    assert _fields(example.CustomerTierUpgraded) == {"customer_id", "new_tier"}
    assert _fields(example.CustomerAddressChanged) == {
        "customer_id",
        "new_street",
        "new_city",
        "new_zip",
    }


def test_saving_a_customer_writes_a_fact_event_with_the_full_state(customers):
    customer = _save_customer(customers)

    payloads = _fact_payloads(customers, customer.customer_id)
    assert len(payloads) == 1
    assert payloads[0]["first_name"] == "Ada"
    assert payloads[0]["last_name"] == "Lovelace"
    assert payloads[0]["email"] == "ada@example.com"
    assert payloads[0]["tier"] == "STANDARD"


def test_a_tier_upgrade_writes_a_new_snapshot_and_a_delta_event(customers):
    customer = _save_customer(customers)
    repo = customers.customers.repository_for(customers.Customer)
    customer = repo.get(customer.customer_id)
    customer.upgrade_tier("GOLD")
    repo.add(customer)

    payloads = _fact_payloads(customers, customer.customer_id)
    assert [p["tier"] for p in payloads] == ["STANDARD", "GOLD"]
    assert payloads[-1]["first_name"] == "Ada"
    assert customers.notifications == [
        ("tier_upgrade", {"customer_id": customer.customer_id, "new_tier": "GOLD"})
    ]


def test_an_address_change_triggers_only_the_address_handler(customers):
    customer = _save_customer(customers)
    repo = customers.customers.repository_for(customers.Customer)
    customer = repo.get(customer.customer_id)
    customer.update_address(
        customers.Address(street="1 Main St", city="London", zip_code="N1")
    )
    repo.add(customer)

    assert customers.notifications == [
        (
            "address_verification",
            {
                "customer_id": customer.customer_id,
                "new_city": "London",
                "new_zip": "N1",
            },
        )
    ]
    snapshot = _fact_payloads(customers, customer.customer_id)[-1]
    assert snapshot["shipping_address"]["city"] == "London"


def _shipping_profiles(envelopes):
    fulfillment = load_example("patterns/fact-events-as-integration-contracts/003.py")
    fulfillment.fulfillment.init(traverse=False)
    with fulfillment.fulfillment.domain_context():
        for envelope in envelopes:
            fulfillment.fulfillment.brokers["default"].publish(
                "customer_fact_events", envelope
            )
        return (
            fulfillment.fulfillment.repository_for(fulfillment.ShippingProfile)
            ._dao.query.all()
            .items
        )


def test_the_fulfillment_subscriber_builds_a_profile_from_a_fact_event(customers):
    customer = _save_customer(customers, phone="555-0100")
    profiles = _shipping_profiles(_fact_envelopes(customers, customer.customer_id))

    assert len(profiles) == 1
    assert profiles[0].customer_id == customer.customer_id
    assert profiles[0].full_name == "Ada Lovelace"
    assert profiles[0].email == "ada@example.com"
    assert profiles[0].phone == "555-0100"
    assert profiles[0].street == ""


def test_the_latest_snapshot_overwrites_the_profile(customers):
    customer = _save_customer(customers)
    repo = customers.customers.repository_for(customers.Customer)
    customer = repo.get(customer.customer_id)
    customer.update_address(
        customers.Address(street="1 Main St", city="London", zip_code="N1")
    )
    customer.upgrade_tier("GOLD")
    repo.add(customer)

    profiles = _shipping_profiles(_fact_envelopes(customers, customer.customer_id))

    assert len(profiles) == 1
    assert profiles[0].street == "1 Main St"
    assert profiles[0].city == "London"
    assert profiles[0].zip_code == "N1"
    assert profiles[0].tier == "GOLD"


def test_the_analytics_subscriber_keeps_only_what_it_needs(customers):
    customer = _save_customer(customers, tier="SILVER")
    envelope = _fact_envelopes(customers, customer.customer_id)[0]

    example = load_example("patterns/fact-events-as-integration-contracts/004.py")
    example.analytics.init(traverse=False)
    with example.analytics.domain_context():
        example.analytics.brokers["default"].publish("customer_fact_events", envelope)
        metrics = example.analytics.repository_for(example.CustomerMetrics).find_by(
            customer_id=customer.customer_id
        )

    assert metrics.tier == "SILVER"
    assert metrics.has_verified_email is True
    assert metrics.has_phone is False
    assert metrics.has_address is False
