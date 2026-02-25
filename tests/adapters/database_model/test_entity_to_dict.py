"""Tests for the shared ``_entity_to_dict`` helper on ``BaseDatabaseModel``.

The helper is the single implementation behind every adapter's
``from_entity()`` method — it iterates attributes, handles value-object
shadow fields, reference fields, and applies ``referenced_as`` remapping.
"""

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.database_model import _entity_to_dict
from protean.core.entity import BaseEntity
from protean.core.value_object import BaseValueObject
from protean.fields import HasMany, Integer, String, ValueObject


# ── Domain elements ──────────────────────────────────────────────────


class Address(BaseValueObject):
    street = String(max_length=100)
    city = String(max_length=50)


class OrderItem(BaseEntity):
    product_name = String(max_length=100, required=True)
    quantity = Integer(default=1)


class Order(BaseAggregate):
    customer_name = String(max_length=50, required=True)
    amount = Integer(default=0)
    items = HasMany(OrderItem)


class PersonWithVO(BaseAggregate):
    name = String(max_length=50, required=True)
    address = ValueObject(Address)


class UserWithReferencedAs(BaseAggregate):
    name = String(max_length=50, referenced_as="full_name")
    age = Integer(default=21, referenced_as="years")


# ── Tests ────────────────────────────────────────────────────────────


class TestEntityToDictBasic:
    """Basic attribute extraction — no VOs, no references, no remapping."""

    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(Order)
        test_domain.register(OrderItem, part_of=Order)
        test_domain.init(traverse=False)

    def test_simple_aggregate_extraction(self, test_domain):
        order = Order(customer_name="Alice", amount=100)
        model_cls = test_domain.repository_for(Order)._database_model
        result = model_cls._entity_to_dict(order)

        assert isinstance(result, dict)
        assert result["customer_name"] == "Alice"
        assert result["amount"] == 100
        # id and _version should be present
        assert "id" in result
        assert "_version" in result

    def test_module_level_function_matches_classmethod(self, test_domain):
        """``_entity_to_dict(cls, entity)`` and ``cls._entity_to_dict(entity)``
        must return the same dict."""
        order = Order(customer_name="Bob", amount=50)
        model_cls = test_domain.repository_for(Order)._database_model

        via_classmethod = model_cls._entity_to_dict(order)
        via_function = _entity_to_dict(model_cls, order)

        assert via_classmethod == via_function


class TestEntityToDictWithValueObject:
    """Value objects are flattened into shadow fields."""

    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(PersonWithVO)
        test_domain.init(traverse=False)

    def test_value_object_fields_are_flattened(self, test_domain):
        person = PersonWithVO(
            name="Charlie",
            address=Address(street="123 Main St", city="Springfield"),
        )
        model_cls = test_domain.repository_for(PersonWithVO)._database_model
        result = model_cls._entity_to_dict(person)

        assert result["name"] == "Charlie"
        # VO shadow fields should appear with their attribute names
        assert result["address_street"] == "123 Main St"
        assert result["address_city"] == "Springfield"
        # The VO field name itself should NOT be a key
        assert "address" not in result


class TestEntityToDictWithReferencedAs:
    """``referenced_as`` remaps the dict key while reading value via field_name."""

    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(UserWithReferencedAs)
        test_domain.init(traverse=False)

    def test_referenced_as_changes_key(self, test_domain):
        user = UserWithReferencedAs(name="Dave", age=30)
        model_cls = test_domain.repository_for(UserWithReferencedAs)._database_model
        result = model_cls._entity_to_dict(user)

        # Keys should use referenced_as names
        assert "full_name" in result
        assert "years" in result
        # Original field names should NOT be keys
        assert "name" not in result
        assert "age" not in result
        # Values should be correct
        assert result["full_name"] == "Dave"
        assert result["years"] == 30


class TestEntityToDictWithReference:
    """Reference fields (HasOne/HasMany parents) produce the FK attribute."""

    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(Order)
        test_domain.register(OrderItem, part_of=Order)
        test_domain.init(traverse=False)

    def test_child_entity_includes_reference_attribute(self, test_domain):
        order = Order(customer_name="Eve", amount=200)
        order.add_items(OrderItem(product_name="Widget", quantity=3))

        # Get the child entity model class
        model_cls = test_domain.repository_for(OrderItem)._database_model
        item = order.items[0]
        result = model_cls._entity_to_dict(item)

        assert result["product_name"] == "Widget"
        assert result["quantity"] == 3
        # The reference to the parent should be included
        assert "order_id" in result
        assert result["order_id"] == order.id
