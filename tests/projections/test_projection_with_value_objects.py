"""Tests for ValueObject support in BaseProjection.

Validates:
- Projection with VO field can be defined and registered
- VO field appears in __container_fields__ correctly
- Projection can be instantiated with VO object directly
- Projection can be instantiated with shadow kwargs
- VO reconstruction from shadow kwargs works
- to_dict() serializes VO correctly
- attributes() returns flattened shadow fields
- Persistence round-trip with Memory provider
- Querying/filtering on shadow field values works
- VO mutation tracking
- None VO handling
- Annotation-style VO declaration
"""

import pytest
from pydantic import Field

from protean.core.projection import BaseProjection
from protean.core.value_object import BaseValueObject
from protean.fields import Identifier, String, ValueObject
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


class CustomerView(BaseProjection):
    customer_id: str = Field(json_schema_extra={"identifier": True})
    name: str = ""
    billing_address = ValueObject(Address)


class CustomerViewAnnotation(BaseProjection):
    customer_id: Identifier(identifier=True)
    name: String()
    shipping_address: ValueObject(Address)


class CustomerViewMultiVO(BaseProjection):
    customer_id: str = Field(json_schema_extra={"identifier": True})
    name: str = ""
    billing_address = ValueObject(Address)
    shipping_address = ValueObject(Address)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Address)
    test_domain.register(CustomerView)
    test_domain.register(CustomerViewAnnotation)
    test_domain.register(CustomerViewMultiVO)
    test_domain.init(traverse=False)


# ---------------------------------------------------------------------------
# Tests: Structure & Reflection
# ---------------------------------------------------------------------------
class TestVOFieldsStructure:
    def test_vo_descriptor_in_container_fields(self):
        cf = getattr(CustomerView, _FIELDS, {})
        assert "billing_address" in cf
        assert isinstance(cf["billing_address"], ValueObject)

    def test_pydantic_fields_coexist_with_vo(self):
        cf = getattr(CustomerView, _FIELDS, {})
        assert "customer_id" in cf
        assert "name" in cf
        assert "billing_address" in cf

    def test_value_object_fields_utility(self):
        vof = value_object_fields(CustomerView)
        assert "billing_address" in vof
        assert isinstance(vof["billing_address"], ValueObject)

    def test_shadow_fields_in_attributes(self):
        attr = attributes(CustomerView)
        assert "billing_address_street" in attr
        assert "billing_address_city" in attr
        assert "billing_address_zip_code" in attr

    def test_annotation_style_vo_in_container_fields(self):
        cf = getattr(CustomerViewAnnotation, _FIELDS, {})
        assert "shipping_address" in cf
        assert isinstance(cf["shipping_address"], ValueObject)

    def test_annotation_style_shadow_fields(self):
        attr = attributes(CustomerViewAnnotation)
        assert "shipping_address_street" in attr
        assert "shipping_address_city" in attr
        assert "shipping_address_zip_code" in attr

    def test_multiple_vo_fields(self):
        cf = getattr(CustomerViewMultiVO, _FIELDS, {})
        assert "billing_address" in cf
        assert "shipping_address" in cf
        assert isinstance(cf["billing_address"], ValueObject)
        assert isinstance(cf["shipping_address"], ValueObject)

    def test_multiple_vo_shadow_fields_distinct(self):
        attr = attributes(CustomerViewMultiVO)
        assert "billing_address_street" in attr
        assert "shipping_address_street" in attr
        assert "billing_address_city" in attr
        assert "shipping_address_city" in attr


# ---------------------------------------------------------------------------
# Tests: Initialization
# ---------------------------------------------------------------------------
class TestVOInitialization:
    def test_init_with_vo_instance(self):
        addr = Address(street="123 Main St", city="Springfield", zip_code="62704")
        view = CustomerView(customer_id="C1", name="Alice", billing_address=addr)
        assert view.billing_address is not None
        assert view.billing_address.street == "123 Main St"
        assert view.billing_address.city == "Springfield"
        assert view.billing_address.zip_code == "62704"

    def test_init_with_shadow_kwargs(self):
        view = CustomerView(
            customer_id="C1",
            name="Alice",
            billing_address_street="123 Main St",
            billing_address_city="Springfield",
            billing_address_zip_code="62704",
        )
        assert view.billing_address is not None
        assert view.billing_address.street == "123 Main St"
        assert view.billing_address.city == "Springfield"

    def test_shadow_kwargs_and_instance_are_equivalent(self):
        addr = Address(street="123 Main St", city="Springfield", zip_code="62704")
        via_instance = CustomerView(
            customer_id="C1", name="Alice", billing_address=addr
        )
        via_flat = CustomerView(
            customer_id="C1",
            name="Alice",
            billing_address_street="123 Main St",
            billing_address_city="Springfield",
            billing_address_zip_code="62704",
        )
        assert via_instance.billing_address == via_flat.billing_address

    def test_none_vo_by_default(self):
        view = CustomerView(customer_id="C1", name="Bob")
        assert view.billing_address is None

    def test_shadow_fields_populated_when_vo_set(self):
        addr = Address(street="123 Main St", city="Springfield", zip_code="62704")
        view = CustomerView(customer_id="C1", name="Alice", billing_address=addr)
        assert view.__dict__["billing_address_street"] == "123 Main St"
        assert view.__dict__["billing_address_city"] == "Springfield"
        assert view.__dict__["billing_address_zip_code"] == "62704"

    def test_shadow_fields_none_when_vo_not_set(self):
        view = CustomerView(customer_id="C1", name="Bob")
        assert view.__dict__.get("billing_address_street") is None
        assert view.__dict__.get("billing_address_city") is None
        assert view.__dict__.get("billing_address_zip_code") is None

    def test_template_dict_with_vo_instance(self):
        addr = Address(street="123 Main St", city="Springfield", zip_code="62704")
        view = CustomerView(
            {"customer_id": "C1", "name": "Alice", "billing_address": addr}
        )
        assert view.billing_address is not None
        assert view.billing_address.street == "123 Main St"

    def test_template_dict_with_shadow_kwargs(self):
        view = CustomerView(
            {
                "customer_id": "C1",
                "name": "Alice",
                "billing_address_street": "123 Main St",
                "billing_address_city": "Springfield",
                "billing_address_zip_code": "62704",
            }
        )
        assert view.billing_address is not None
        assert view.billing_address.street == "123 Main St"

    def test_annotation_style_init_with_vo(self):
        addr = Address(street="456 Elm Ave", city="Shelbyville", zip_code="62705")
        view = CustomerViewAnnotation(
            customer_id="C1", name="Alice", shipping_address=addr
        )
        assert view.shipping_address.street == "456 Elm Ave"

    def test_annotation_style_init_with_shadow_kwargs(self):
        view = CustomerViewAnnotation(
            customer_id="C1",
            name="Alice",
            shipping_address_street="456 Elm Ave",
            shipping_address_city="Shelbyville",
            shipping_address_zip_code="62705",
        )
        assert view.shipping_address is not None
        assert view.shipping_address.street == "456 Elm Ave"


# ---------------------------------------------------------------------------
# Tests: Mutation
# ---------------------------------------------------------------------------
class TestVOMutation:
    def test_replace_vo(self):
        addr1 = Address(street="123 Main St", city="Springfield", zip_code="62704")
        view = CustomerView(customer_id="C1", name="Alice", billing_address=addr1)

        addr2 = Address(street="456 Elm Ave", city="Shelbyville", zip_code="62705")
        view.billing_address = addr2
        assert view.billing_address == addr2
        assert view.__dict__["billing_address_street"] == "456 Elm Ave"
        assert view.__dict__["billing_address_city"] == "Shelbyville"

    def test_set_vo_to_none(self):
        addr = Address(street="123 Main St", city="Springfield", zip_code="62704")
        view = CustomerView(customer_id="C1", name="Alice", billing_address=addr)
        view.billing_address = None
        assert view.billing_address is None

    def test_vo_mutation_marks_changed(self):
        view = CustomerView(customer_id="C1", name="Alice")
        view._state.mark_saved()
        assert not view._state.is_changed

        view.billing_address = Address(street="789 Oak Ln")
        assert view._state.is_changed


# ---------------------------------------------------------------------------
# Tests: Serialization
# ---------------------------------------------------------------------------
class TestVOSerialization:
    def test_to_dict_includes_vo(self):
        addr = Address(street="123 Main St", city="Springfield", zip_code="62704")
        view = CustomerView(customer_id="C1", name="Alice", billing_address=addr)
        d = view.to_dict()
        assert "billing_address" in d
        assert d["billing_address"]["street"] == "123 Main St"
        assert d["billing_address"]["city"] == "Springfield"
        assert d["billing_address"]["zip_code"] == "62704"

    def test_to_dict_none_vo(self):
        view = CustomerView(customer_id="C1", name="Bob")
        d = view.to_dict()
        # None VOs serialize as None
        assert d["billing_address"] is None

    def test_to_dict_regular_fields_unaffected(self):
        addr = Address(street="123 Main St", city="Springfield", zip_code="62704")
        view = CustomerView(customer_id="C1", name="Alice", billing_address=addr)
        d = view.to_dict()
        assert d["customer_id"] == "C1"
        assert d["name"] == "Alice"

    def test_to_dict_with_multiple_vos(self):
        addr1 = Address(street="123 Main St", city="Springfield", zip_code="62704")
        addr2 = Address(street="456 Elm Ave", city="Shelbyville", zip_code="62705")
        view = CustomerViewMultiVO(
            customer_id="C1",
            name="Alice",
            billing_address=addr1,
            shipping_address=addr2,
        )
        d = view.to_dict()
        assert d["billing_address"]["street"] == "123 Main St"
        assert d["shipping_address"]["street"] == "456 Elm Ave"


# ---------------------------------------------------------------------------
# Tests: Edge cases for coverage
# ---------------------------------------------------------------------------
class TestVOEdgeCases:
    def test_model_post_init_without_init_context(self):
        """Ensure model_post_init handles an empty thread-local stack gracefully.

        This exercises the defensive else branch in model_post_init when
        the thread-local stack has been consumed or is absent.
        """
        from protean.core.projection import _projection_init_context

        view = CustomerView(customer_id="C1", name="Alice")
        # Clear the thread-local stack, then call model_post_init directly
        _projection_init_context.stack = []
        view._initialized = False
        view.model_post_init(None)
        # Should not crash; VO remains None
        assert view.billing_address is None

    def test_setting_identifier_to_same_value_is_allowed(self):
        """Setting the identifier field to its current value should not raise."""
        view = CustomerView(customer_id="C1", name="Alice")
        # Re-setting the same value should succeed silently
        view.customer_id = "C1"
        assert view.customer_id == "C1"


# ---------------------------------------------------------------------------
# Tests: Persistence round-trip
# ---------------------------------------------------------------------------
@pytest.mark.database
@pytest.mark.usefixtures("db")
class TestVOPersistence:
    def test_persist_and_retrieve_with_vo(self, test_domain):
        addr = Address(street="123 Main St", city="Springfield", zip_code="62704")
        view = CustomerView(customer_id="C1", name="Alice", billing_address=addr)
        test_domain.repository_for(CustomerView).add(view)

        refreshed = test_domain.repository_for(CustomerView).get("C1")
        assert refreshed.billing_address is not None
        assert refreshed.billing_address.street == "123 Main St"
        assert refreshed.billing_address.city == "Springfield"
        assert refreshed.billing_address.zip_code == "62704"

    def test_persist_and_retrieve_without_vo(self, test_domain):
        view = CustomerView(customer_id="C2", name="Bob")
        test_domain.repository_for(CustomerView).add(view)

        refreshed = test_domain.repository_for(CustomerView).get("C2")
        assert refreshed.billing_address is None

    def test_update_vo_and_retrieve(self, test_domain):
        addr = Address(street="123 Main St", city="Springfield", zip_code="62704")
        view = CustomerView(customer_id="C1", name="Alice", billing_address=addr)
        test_domain.repository_for(CustomerView).add(view)

        view.billing_address = Address(
            street="456 Elm Ave", city="Shelbyville", zip_code="62705"
        )
        test_domain.repository_for(CustomerView).add(view)

        refreshed = test_domain.repository_for(CustomerView).get("C1")
        assert refreshed.billing_address.street == "456 Elm Ave"
        assert refreshed.billing_address.city == "Shelbyville"

    def test_filter_on_shadow_field(self, test_domain):
        addr1 = Address(street="123 Main St", city="Springfield", zip_code="62704")
        addr2 = Address(street="456 Elm Ave", city="Shelbyville", zip_code="62705")
        test_domain.repository_for(CustomerView).add(
            CustomerView(customer_id="C1", name="Alice", billing_address=addr1)
        )
        test_domain.repository_for(CustomerView).add(
            CustomerView(customer_id="C2", name="Bob", billing_address=addr2)
        )

        results = (
            test_domain.repository_for(CustomerView)
            .query.filter(billing_address_city="Springfield")
            .all()
        )
        assert len(results) == 1
        assert results.first.customer_id == "C1"

    def test_persist_multiple_vos(self, test_domain):
        addr1 = Address(street="123 Main St", city="Springfield", zip_code="62704")
        addr2 = Address(street="456 Elm Ave", city="Shelbyville", zip_code="62705")
        view = CustomerViewMultiVO(
            customer_id="C1",
            name="Alice",
            billing_address=addr1,
            shipping_address=addr2,
        )
        test_domain.repository_for(CustomerViewMultiVO).add(view)

        refreshed = test_domain.repository_for(CustomerViewMultiVO).get("C1")
        assert refreshed.billing_address.street == "123 Main St"
        assert refreshed.shipping_address.street == "456 Elm Ave"
