"""Tests for IRBuilder field extraction."""

import pytest

from protean.ir.builder import IRBuilder

from .elements import (
    build_extended_field_test_domain,
    build_field_test_domain,
    build_status_field_domain,
)


@pytest.fixture
def product_fields():
    """Return extracted fields for the Product aggregate."""
    domain = build_field_test_domain()
    builder = IRBuilder(domain)
    product_cls = None
    for record in domain._domain_registry._elements["AGGREGATE"].values():
        if record.cls.__name__ == "Product":
            product_cls = record.cls
            break
    assert product_cls is not None
    return builder._extract_fields(product_cls)


@pytest.mark.no_test_domain
class TestFieldKinds:
    """Verify each field kind is correctly identified."""

    def test_standard_string(self, product_fields):
        f = product_fields["name"]
        assert f["kind"] == "standard"
        assert f["type"] == "String"

    def test_text_field(self, product_fields):
        f = product_fields["description"]
        assert f["kind"] == "text"
        assert f["type"] == "Text"

    def test_float_field(self, product_fields):
        f = product_fields["price"]
        assert f["kind"] == "standard"
        assert f["type"] == "Float"

    def test_integer_field(self, product_fields):
        f = product_fields["quantity"]
        assert f["kind"] == "standard"
        assert f["type"] == "Integer"

    def test_boolean_field(self, product_fields):
        f = product_fields["is_active"]
        assert f["kind"] == "standard"
        assert f["type"] == "Boolean"

    def test_datetime_field(self, product_fields):
        f = product_fields["created_at"]
        assert f["kind"] == "standard"
        assert f["type"] == "DateTime"

    def test_date_field(self, product_fields):
        f = product_fields["launch_date"]
        assert f["kind"] == "standard"
        assert f["type"] == "Date"

    def test_identifier_field(self, product_fields):
        f = product_fields["sku"]
        assert f["kind"] == "identifier"
        assert f["type"] == "Identifier"

    def test_auto_field(self, product_fields):
        f = product_fields["id"]
        assert f["kind"] == "auto"
        assert f["type"] == "Auto"

    def test_list_field(self, product_fields):
        f = product_fields["tags"]
        assert f["kind"] == "list"
        assert f["type"] == "List"

    def test_dict_field(self, product_fields):
        f = product_fields["metadata_field"]
        assert f["kind"] == "dict"
        assert f["type"] == "Dict"

    def test_value_object_field(self, product_fields):
        f = product_fields["shipping_address"]
        assert f["kind"] == "value_object"
        assert "target" in f

    def test_has_many_field(self, product_fields):
        f = product_fields["variants"]
        assert f["kind"] == "has_many"
        assert "target" in f


@pytest.mark.no_test_domain
class TestSparseRepresentation:
    """Verify only non-default attributes are emitted."""

    def test_required_only_when_true(self, product_fields):
        assert product_fields["name"].get("required") is True
        assert "required" not in product_fields["price"]

    def test_identifier_only_when_true(self, product_fields):
        assert product_fields["id"].get("identifier") is True
        assert "identifier" not in product_fields["name"]

    def test_unique_not_duplicated_for_identifier(self, product_fields):
        # identifier implies unique — unique should not appear separately
        assert "unique" not in product_fields["id"]

    def test_auto_generated_only_when_true(self, product_fields):
        assert product_fields["id"].get("auto_generated") is True
        assert "auto_generated" not in product_fields["name"]

    def test_max_length_only_when_set(self, product_fields):
        assert product_fields["name"]["max_length"] == 200
        assert "max_length" not in product_fields["price"]

    def test_min_value_only_when_set(self, product_fields):
        assert product_fields["price"]["min_value"] == 0.0
        assert "min_value" not in product_fields["name"]

    def test_sanitize_only_when_true(self, product_fields):
        assert product_fields["name"].get("sanitize") is True
        assert "sanitize" not in product_fields["price"]


@pytest.mark.no_test_domain
class TestDefaultSerialization:
    """Verify default values are serialized correctly."""

    def test_literal_default(self, product_fields):
        assert product_fields["is_active"]["default"] is True

    def test_numeric_default(self, product_fields):
        assert product_fields["score"]["default"] == 0.0

    def test_no_default_omits_key(self, product_fields):
        # name has no default
        assert "default" not in product_fields["name"]


@pytest.mark.no_test_domain
class TestChoices:
    """Verify choices are extracted as sorted lists."""

    def test_choices_present(self, product_fields):
        assert "choices" in product_fields["status"]
        assert product_fields["status"]["choices"] == [
            "ACTIVE",
            "ARCHIVED",
            "INACTIVE",
        ]


@pytest.mark.no_test_domain
class TestContentType:
    """Verify content_type for List fields."""

    def test_list_content_type(self, product_fields):
        assert product_fields["tags"].get("content_type") == "String"


@pytest.mark.no_test_domain
class TestFieldsSorted:
    """Verify field dict keys are sorted alphabetically."""

    def test_keys_sorted(self, product_fields):
        for name, field_dict in product_fields.items():
            keys = list(field_dict.keys())
            assert keys == sorted(keys), f"Keys not sorted for field '{name}': {keys}"

    def test_field_names_sorted(self, product_fields):
        names = list(product_fields.keys())
        assert names == sorted(names)


# ---------------------------------------------------------------------------
# Extended field tests — HasOne, callable default, description
# ---------------------------------------------------------------------------


@pytest.fixture
def catalog_fields():
    """Return extracted fields for the Catalog aggregate."""
    domain = build_extended_field_test_domain()
    builder = IRBuilder(domain)
    catalog_cls = None
    for record in domain._domain_registry._elements["AGGREGATE"].values():
        if record.cls.__name__ == "Catalog":
            catalog_cls = record.cls
            break
    assert catalog_cls is not None
    return builder._extract_fields(catalog_cls)


@pytest.mark.no_test_domain
class TestHasOneField:
    """Verify HasOne field extraction."""

    def test_has_one_kind(self, catalog_fields):
        f = catalog_fields["featured"]
        assert f["kind"] == "has_one"

    def test_has_one_target(self, catalog_fields):
        f = catalog_fields["featured"]
        assert "target" in f
        assert "FeaturedItem" in f["target"]


@pytest.mark.no_test_domain
class TestCallableDefault:
    """Verify callable defaults serialize as '<callable>'."""

    def test_callable_default_is_string(self, catalog_fields):
        f = catalog_fields["items_cache"]
        assert f["default"] == "<callable>"


@pytest.mark.no_test_domain
class TestFieldDescription:
    """Verify description attribute extraction."""

    def test_description_present(self, catalog_fields):
        f = catalog_fields["name"]
        assert f["description"] == "Catalog name"

    def test_description_absent_when_not_set(self, catalog_fields):
        f = catalog_fields["items_cache"]
        assert "description" not in f


# ---------------------------------------------------------------------------
# Status field IR extraction tests
# ---------------------------------------------------------------------------


@pytest.fixture
def status_fields():
    """Return extracted fields for the Order aggregate with Status fields."""
    domain = build_status_field_domain()
    builder = IRBuilder(domain)
    order_cls = None
    for record in domain._domain_registry._elements["AGGREGATE"].values():
        if record.cls.__name__ == "Order":
            order_cls = record.cls
            break
    assert order_cls is not None
    return builder._extract_fields(order_cls)


@pytest.mark.no_test_domain
class TestStatusFieldExtraction:
    """Verify Status field kind, type, and transitions in IR."""

    def test_status_kind(self, status_fields):
        f = status_fields["status"]
        assert f["kind"] == "status"

    def test_status_type(self, status_fields):
        f = status_fields["status"]
        assert f["type"] == "Status"

    def test_status_transitions_present(self, status_fields):
        f = status_fields["status"]
        assert "transitions" in f
        assert f["transitions"] == {
            "DRAFT": ["PLACED", "CANCELLED"],
            "PLACED": ["CONFIRMED"],
            "CONFIRMED": ["SHIPPED"],
        }

    def test_status_choices_present(self, status_fields):
        f = status_fields["status"]
        assert "choices" in f
        assert "DRAFT" in f["choices"]

    def test_status_without_transitions(self, status_fields):
        """Status field without transitions should not have transitions key."""
        f = status_fields["category"]
        assert f["kind"] == "status"
        assert f["type"] == "Status"
        assert "transitions" not in f

    def test_status_default(self, status_fields):
        f = status_fields["status"]
        assert f["default"] == "DRAFT"
