"""Run the examples on ``docs/concepts/internals/shadow-fields.md``."""

import pytest

from protean.exceptions import ValidationError
from protean.utils.reflection import attributes
from tests.docs.support import load_example

pytestmark = pytest.mark.no_test_domain

_BILLING_SHADOWS = {
    "billing_address_street",
    "billing_address_city",
    "billing_address_zip_code",
}


def _context(example):
    example.domain.init(traverse=False)
    return example.domain.domain_context()


def test_value_object_fields_become_shadow_fields():
    example = load_example("concepts/internals/shadow-fields/001.py")
    with _context(example):
        fields = attributes(example.Customer)

        assert {name: type(field).__name__ for name, field in fields.items()} == {
            "name": "ResolvedField",
            "id": "ResolvedField",
            "billing_address_street": "_ShadowField",
            "billing_address_city": "_ShadowField",
            "billing_address_zip_code": "_ShadowField",
            "_version": "ResolvedField",
        }


def test_reference_becomes_an_id_shadow_field():
    example = load_example("concepts/internals/shadow-fields/001.py")
    with _context(example):
        fields = attributes(example.LineItem)

        assert "order_id" in fields
        assert "order" not in fields


def test_referenced_as_renames_the_shadow_fields():
    example = load_example("concepts/internals/shadow-fields/002.py")
    with _context(example):
        line_item_fields = attributes(example.LineItem)
        assert "order_number" in line_item_fields
        assert "order_id" not in line_item_fields

        supplier_fields = attributes(example.Supplier)
        assert {"addr_street", "addr_city"} <= set(supplier_fields)
        assert not {"billing_address_street", "billing_address_city"} & set(
            supplier_fields
        )

        supplier = example.Supplier(name="Acme", addr_street="1 Dock", addr_city="Oslo")
        assert supplier.billing_address == example.SupplierAddress(
            street="1 Dock", city="Oslo"
        )

        # The default names are gone, so passing them is an error
        with pytest.raises(ValidationError) as exc:
            example.Supplier(name="Acme", billing_address_street="1 Dock")
        assert exc.value.messages == {
            "billing_address_street": ["Extra inputs are not permitted"]
        }


def test_shadow_fields_are_not_pydantic_fields():
    example = load_example("concepts/internals/shadow-fields/001.py")
    with _context(example):
        customer = example.Customer(
            name="Alice",
            billing_address=example.Address(
                street="123 Main", city="NYC", zip_code="10001"
            ),
        )

        assert not _BILLING_SHADOWS & set(example.Customer.model_fields)
        assert not _BILLING_SHADOWS & set(customer.model_dump())
        schema = example.Customer.model_json_schema()
        assert not _BILLING_SHADOWS & set(schema["properties"])

        data = customer.to_dict()
        assert not _BILLING_SHADOWS & set(data)
        assert data["billing_address"] == {
            "street": "123 Main",
            "city": "NYC",
            "zip_code": "10001",
        }

        # Direct access still reads them
        assert customer.billing_address_street == "123 Main"


def test_shadow_kwargs_rebuild_the_value_object():
    example = load_example("concepts/internals/shadow-fields/001.py")
    with _context(example):
        from_object = example.Customer(
            name="Alice",
            billing_address=example.Address(
                street="123 Main", city="NYC", zip_code="10001"
            ),
        )
        from_shadows = example.Customer(
            name="Alice",
            billing_address_street="123 Main",
            billing_address_city="NYC",
            billing_address_zip_code="10001",
        )

        assert from_shadows.billing_address == from_object.billing_address
        for name in _BILLING_SHADOWS:
            assert from_shadows.__dict__[name] == from_object.__dict__[name]


def test_assigning_the_value_object_updates_the_shadow_fields():
    example = load_example("concepts/internals/shadow-fields/001.py")
    with _context(example):
        customer = example.Customer(name="Alice")

        customer.billing_address = example.Address(
            street="456 Oak", city="LA", zip_code="90001"
        )
        assert customer.__dict__["billing_address_street"] == "456 Oak"
        assert customer.__dict__["billing_address_city"] == "LA"
        assert customer.__dict__["billing_address_zip_code"] == "90001"

        customer.billing_address = None
        assert all(customer.__dict__.get(name) is None for name in _BILLING_SHADOWS)


def test_writing_a_shadow_field_marks_the_entity_changed():
    example = load_example("concepts/internals/shadow-fields/001.py")
    with _context(example):
        customer = example.Customer(name="Alice", billing_address_street="456 Oak")
        customer.state_.mark_saved()
        assert not customer.state_.is_changed

        customer.billing_address_street = "789 Pine"

        assert customer.billing_address_street == "789 Pine"
        assert customer.state_.is_changed


def test_page_walkthrough_ends_with_the_direct_write():
    # The lifecycle sections run in page order on one customer
    example = load_example("concepts/internals/shadow-fields/001.py")

    assert example.customer.billing_address_street == "789 Pine"
    assert example.customer.billing_address_city == "LA"
    assert example.customer.billing_address_zip_code == "90001"
