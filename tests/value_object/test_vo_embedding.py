"""Tests for ValueObject embedding in BaseEntity / BaseAggregate.

Validates:
- VO assignment and access
- Shadow fields in attributes()
- None handling
- to_dict() serialization
- State tracking on VO change
- Domain registration
"""

from uuid import uuid4

import pytest
from pydantic import Field

from protean.core.aggregate import BaseAggregate
from protean.core.value_object import BaseValueObject
from protean.fields import ValueObject
from protean.utils import fully_qualified_name
from protean.utils.reflection import (
    _FIELDS,
    attributes,
    value_object_fields,
)


# ---------------------------------------------------------------------------
# Test domain elements
# ---------------------------------------------------------------------------
class Address(BaseValueObject):
    street: str = ""
    city: str = ""
    zip_code: str = ""


class Customer(BaseAggregate):
    id: str = Field(
        json_schema_extra={"identifier": True},
        default_factory=lambda: str(uuid4()),
    )
    name: str = ""
    billing_address = ValueObject(Address)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Address)
    test_domain.register(Customer)
    test_domain.init(traverse=False)


# ---------------------------------------------------------------------------
# Tests: __container_fields__ bridge
# ---------------------------------------------------------------------------
class TestVOFieldsBridge:
    def test_vo_descriptor_in_container_fields(self):
        cf = getattr(Customer, _FIELDS, {})
        assert "billing_address" in cf
        assert isinstance(cf["billing_address"], ValueObject)

    def test_annotated_fields_coexist(self):
        cf = getattr(Customer, _FIELDS, {})
        assert "id" in cf
        assert "name" in cf

    def test_value_object_fields_utility(self):
        vof = value_object_fields(Customer)
        assert "billing_address" in vof

    def test_shadow_fields_in_attributes(self):
        attr = attributes(Customer)
        assert "billing_address_street" in attr
        assert "billing_address_city" in attr
        assert "billing_address_zip_code" in attr


# ---------------------------------------------------------------------------
# Tests: Assignment and access
# ---------------------------------------------------------------------------
class TestVOAssignment:
    def test_assign_vo_at_construction(self):
        addr = Address(street="123 Main St", city="Springfield", zip_code="62704")
        customer = Customer(name="Alice", billing_address=addr)

        assert customer.billing_address == addr
        assert customer.billing_address.street == "123 Main St"

    def test_shadow_fields_populated(self):
        addr = Address(street="123 Main St", city="Springfield", zip_code="62704")
        customer = Customer(name="Alice", billing_address=addr)

        assert customer.__dict__["billing_address_street"] == "123 Main St"
        assert customer.__dict__["billing_address_city"] == "Springfield"
        assert customer.__dict__["billing_address_zip_code"] == "62704"

    def test_none_vo_by_default(self):
        customer = Customer(name="Bob")
        assert customer.billing_address is None

    def test_replace_vo(self):
        addr1 = Address(street="123 Main St", city="Springfield", zip_code="62704")
        customer = Customer(name="Alice", billing_address=addr1)

        addr2 = Address(street="456 Elm Ave", city="Shelbyville", zip_code="62705")
        customer.billing_address = addr2

        assert customer.billing_address == addr2
        assert customer.__dict__["billing_address_street"] == "456 Elm Ave"

    def test_set_vo_to_none(self):
        addr = Address(street="123 Main St", city="Springfield", zip_code="62704")
        customer = Customer(name="Alice", billing_address=addr)

        customer.billing_address = None
        assert customer.billing_address is None


# ---------------------------------------------------------------------------
# Tests: State tracking
# ---------------------------------------------------------------------------
class TestVOStateTracking:
    def test_setting_vo_marks_changed(self):
        customer = Customer(name="Alice")
        customer._state.mark_saved()
        assert not customer._state.is_changed

        customer.billing_address = Address(street="789 Oak Ln")
        assert customer._state.is_changed


# ---------------------------------------------------------------------------
# Tests: Serialization
# ---------------------------------------------------------------------------
class TestVOSerialization:
    def test_to_dict_includes_vo(self):
        addr = Address(street="123 Main St", city="Springfield", zip_code="62704")
        customer = Customer(name="Alice", billing_address=addr)
        d = customer.to_dict()

        assert "billing_address" in d
        assert d["billing_address"]["street"] == "123 Main St"
        assert d["billing_address"]["city"] == "Springfield"
        assert d["billing_address"]["zip_code"] == "62704"

    def test_to_dict_excludes_none_vo(self):
        customer = Customer(name="Bob")
        d = customer.to_dict()

        # ValueObject field should not appear when None
        assert "billing_address" not in d

    def test_to_dict_annotated_fields_included(self):
        customer = Customer(name="Alice")
        d = customer.to_dict()

        assert d["name"] == "Alice"
        assert "id" in d


# ---------------------------------------------------------------------------
# Tests: Domain registration
# ---------------------------------------------------------------------------
class TestVODomainRegistration:
    def test_aggregate_with_vo_registered(self, test_domain):
        assert fully_qualified_name(Customer) in test_domain.registry.aggregates

    def test_vo_registered(self, test_domain):
        assert fully_qualified_name(Address) in test_domain.registry.value_objects
