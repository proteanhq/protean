"""Tests for the unified ``to_entity()`` in ``BaseDatabaseModel`` and the
``_get_value()`` hook that adapters override for storage-specific access.

E1: The base class provides a default ``to_entity()`` that iterates attributes,
applies ``referenced_as`` remapping, and reconstructs the domain entity.
Adapters customize only ``_get_value()`` — Memory overrides for dict access,
SQLAlchemy uses the default ``getattr()``, and Elasticsearch keeps a full
override for its meta.id/version-specific logic.
"""

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.value_object import BaseValueObject
from protean.fields import Integer, String, ValueObject


# ── Domain elements ──────────────────────────────────────────────────


class Address(BaseValueObject):
    street = String(max_length=100)
    city = String(max_length=50)


class PersonSimple(BaseAggregate):
    first_name = String(max_length=50, required=True)
    last_name = String(max_length=50, required=True)
    age = Integer(default=21)


class PersonWithVO(BaseAggregate):
    name = String(max_length=50, required=True)
    address = ValueObject(Address)


class PersonWithReferencedAs(BaseAggregate):
    name = String(max_length=50, referenced_as="full_name")
    age = Integer(default=21, referenced_as="years")


# ── Tests ────────────────────────────────────────────────────────────


class TestBaseToEntity:
    """The default ``to_entity()`` on ``BaseDatabaseModel`` should work
    with any record type as long as ``_get_value()`` is appropriate."""

    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(PersonSimple)
        test_domain.init(traverse=False)

    def test_roundtrip_entity_to_model_and_back(self, test_domain):
        person = PersonSimple(first_name="Alice", last_name="Smith", age=30)
        model_cls = test_domain.repository_for(PersonSimple)._database_model
        model_obj = model_cls.from_entity(person)
        restored = model_cls.to_entity(model_obj)

        assert restored.first_name == "Alice"
        assert restored.last_name == "Smith"
        assert restored.age == 30
        assert restored.id == person.id

    def test_to_entity_preserves_identity(self, test_domain):
        person = PersonSimple(first_name="Bob", last_name="Jones", age=25)
        model_cls = test_domain.repository_for(PersonSimple)._database_model
        model_obj = model_cls.from_entity(person)
        restored = model_cls.to_entity(model_obj)

        assert restored.id == person.id


class TestToEntityWithValueObject:
    """``to_entity()`` must correctly reconstruct value objects from
    flattened shadow fields."""

    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(PersonWithVO)
        test_domain.init(traverse=False)

    def test_value_object_roundtrip(self, test_domain):
        person = PersonWithVO(
            name="Charlie",
            address=Address(street="123 Main St", city="Springfield"),
        )
        model_cls = test_domain.repository_for(PersonWithVO)._database_model
        model_obj = model_cls.from_entity(person)
        restored = model_cls.to_entity(model_obj)

        assert restored.name == "Charlie"
        assert restored.address.street == "123 Main St"
        assert restored.address.city == "Springfield"

    def test_none_value_object_roundtrip(self, test_domain):
        person = PersonWithVO(name="Dave")
        model_cls = test_domain.repository_for(PersonWithVO)._database_model
        model_obj = model_cls.from_entity(person)
        restored = model_cls.to_entity(model_obj)

        assert restored.name == "Dave"
        assert restored.address is None


class TestToEntityWithReferencedAs:
    """``to_entity()`` must remap ``referenced_as`` keys back to field names."""

    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(PersonWithReferencedAs)
        test_domain.init(traverse=False)

    def test_referenced_as_roundtrip(self, test_domain):
        person = PersonWithReferencedAs(name="Eve", age=35)
        model_cls = test_domain.repository_for(PersonWithReferencedAs)._database_model
        model_obj = model_cls.from_entity(person)
        restored = model_cls.to_entity(model_obj)

        assert restored.name == "Eve"
        assert restored.age == 35


class TestMemoryGetValueOverride:
    """Memory adapter overrides ``_get_value()`` for dict-based access."""

    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(PersonSimple)
        test_domain.init(traverse=False)

    def test_memory_model_get_value_uses_dict_access(self, test_domain):
        from protean.adapters.repository.memory import MemoryModel

        model_cls = test_domain.repository_for(PersonSimple)._database_model
        assert issubclass(model_cls, MemoryModel)

        # MemoryModel.from_entity() returns a dict
        person = PersonSimple(first_name="Frank", last_name="Brown", age=40)
        record = model_cls.from_entity(person)
        assert isinstance(record, dict)

        # _get_value should use dict key access
        assert model_cls._get_value(record, "first_name") == "Frank"
        assert model_cls._get_value(record, "age") == 40

    def test_memory_model_to_entity_uses_base_implementation(self, test_domain):
        """MemoryModel should use the base to_entity() — it no longer overrides it."""
        from protean.adapters.repository.memory import MemoryModel

        # Verify that MemoryModel does NOT define its own to_entity
        assert "to_entity" not in MemoryModel.__dict__
        # But it's still available via inheritance
        assert hasattr(MemoryModel, "to_entity")


class TestSqlalchemyGetValueDefault:
    """SQLAlchemy adapter uses the base ``_get_value()`` default (``getattr``)."""

    def test_sqlalchemy_model_does_not_override_to_entity(self):
        from protean.adapters.repository.sqlalchemy import SqlalchemyModel

        # SqlalchemyModel should NOT define its own to_entity or _get_value
        assert "to_entity" not in SqlalchemyModel.__dict__
        assert "_get_value" not in SqlalchemyModel.__dict__
        # Both should be inherited from BaseDatabaseModel
        assert hasattr(SqlalchemyModel, "to_entity")
        assert hasattr(SqlalchemyModel, "_get_value")
