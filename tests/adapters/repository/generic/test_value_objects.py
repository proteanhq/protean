"""Generic value object persistence tests that run against all database providers.

Covers embedded ValueObject persistence, update, and round-trip fidelity
for both required and optional value objects.
"""

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.value_object import BaseValueObject
from protean.fields import String, ValueObject


class Email(BaseValueObject):
    address: String(max_length=254, required=True)


class Address(BaseValueObject):
    street: String(max_length=100)
    city: String(max_length=50)
    zip_code: String(max_length=10)


class Customer(BaseAggregate):
    name: String(max_length=100, required=True)
    email = ValueObject(Email, required=True)
    billing_address = ValueObject(Address)


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Customer)
    test_domain.register(Email, part_of=Customer)
    test_domain.register(Address, part_of=Customer)
    test_domain.init(traverse=False)


@pytest.mark.basic_storage
class TestValueObjectPersistence:
    """Persist aggregates with embedded VOs and verify retrieval."""

    def test_persist_aggregate_with_required_value_object(self, test_domain):
        customer = Customer(
            name="Alice",
            email=Email(address="alice@example.com"),
        )
        test_domain.repository_for(Customer).add(customer)

        retrieved = test_domain.repository_for(Customer).get(customer.id)
        assert retrieved.name == "Alice"
        assert retrieved.email_address == "alice@example.com"

    def test_persist_aggregate_with_optional_value_object_set(self, test_domain):
        customer = Customer(
            name="Bob",
            email=Email(address="bob@example.com"),
            billing_address=Address(
                street="123 Main St", city="Springfield", zip_code="62704"
            ),
        )
        test_domain.repository_for(Customer).add(customer)

        retrieved = test_domain.repository_for(Customer).get(customer.id)
        assert retrieved.billing_address_street == "123 Main St"
        assert retrieved.billing_address_city == "Springfield"
        assert retrieved.billing_address_zip_code == "62704"

    def test_persist_aggregate_with_optional_value_object_none(self, test_domain):
        customer = Customer(
            name="Charlie",
            email=Email(address="charlie@example.com"),
            billing_address=None,
        )
        test_domain.repository_for(Customer).add(customer)

        retrieved = test_domain.repository_for(Customer).get(customer.id)
        assert retrieved.billing_address is None


@pytest.mark.basic_storage
class TestValueObjectUpdate:
    """Update VO fields on a persisted aggregate and verify changes."""

    def test_update_required_value_object(self, test_domain):
        customer = Customer(
            name="Alice",
            email=Email(address="alice@example.com"),
        )
        test_domain.repository_for(Customer).add(customer)

        # Retrieve, update, and re-persist
        retrieved = test_domain.repository_for(Customer).get(customer.id)
        retrieved.email = Email(address="newalice@example.com")
        test_domain.repository_for(Customer).add(retrieved)

        updated = test_domain.repository_for(Customer).get(customer.id)
        assert updated.email_address == "newalice@example.com"

    def test_update_optional_value_object_from_none(self, test_domain):
        customer = Customer(
            name="Bob",
            email=Email(address="bob@example.com"),
        )
        test_domain.repository_for(Customer).add(customer)

        # Set previously-None optional VO
        retrieved = test_domain.repository_for(Customer).get(customer.id)
        retrieved.billing_address = Address(
            street="456 Oak Ave", city="Shelbyville", zip_code="62705"
        )
        test_domain.repository_for(Customer).add(retrieved)

        updated = test_domain.repository_for(Customer).get(customer.id)
        assert updated.billing_address_street == "456 Oak Ave"
        assert updated.billing_address_city == "Shelbyville"

    def test_update_optional_value_object_values(self, test_domain):
        customer = Customer(
            name="Charlie",
            email=Email(address="charlie@example.com"),
            billing_address=Address(
                street="789 Elm St", city="Capital City", zip_code="62706"
            ),
        )
        test_domain.repository_for(Customer).add(customer)

        # Replace the optional VO with new values
        retrieved = test_domain.repository_for(Customer).get(customer.id)
        retrieved.billing_address = Address(
            street="101 New St", city="New City", zip_code="99999"
        )
        test_domain.repository_for(Customer).add(retrieved)

        updated = test_domain.repository_for(Customer).get(customer.id)
        assert updated.billing_address_street == "101 New St"
        assert updated.billing_address_city == "New City"
        assert updated.billing_address_zip_code == "99999"

    def test_update_optional_value_object_to_none(self, test_domain):
        customer = Customer(
            name="Dana",
            email=Email(address="dana@example.com"),
            billing_address=Address(
                street="789 Elm St", city="Capital City", zip_code="62706"
            ),
        )
        test_domain.repository_for(Customer).add(customer)

        # Clear the optional VO
        retrieved = test_domain.repository_for(Customer).get(customer.id)
        retrieved.billing_address = None
        test_domain.repository_for(Customer).add(retrieved)

        updated = test_domain.repository_for(Customer).get(customer.id)
        assert updated.billing_address is None


@pytest.mark.basic_storage
class TestValueObjectRoundTrip:
    """Verify complete round-trip fidelity of all VO attributes."""

    def test_full_round_trip_with_all_value_objects(self, test_domain):
        customer = Customer(
            name="Diana",
            email=Email(address="diana@example.com"),
            billing_address=Address(
                street="101 Pine Rd", city="Ogdenville", zip_code="62707"
            ),
        )
        test_domain.repository_for(Customer).add(customer)

        retrieved = test_domain.repository_for(Customer).get(customer.id)

        assert retrieved.id == customer.id
        assert retrieved.name == customer.name
        assert retrieved.email_address == customer.email_address
        assert retrieved.billing_address_street == customer.billing_address_street
        assert retrieved.billing_address_city == customer.billing_address_city
        assert retrieved.billing_address_zip_code == customer.billing_address_zip_code
