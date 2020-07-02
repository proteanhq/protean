# Protean
from protean.core.entity import EntityMeta
from protean.core.field.basic import Auto, Integer, String

# Local/Relative Imports
from .elements import (
    AbstractPerson,
    Adult,
    AdultAbstractPerson,
    ConcretePerson,
    DbPerson,
    DifferentDbPerson,
    OrderedPerson,
    OrderedPersonSubclass,
    Person,
    SqlDifferentDbPerson,
    SqlPerson,
)


class TestEntityMeta:
    def test_entity_meta_structure(self):
        assert hasattr(Person, "meta_")
        assert type(Person.meta_) is EntityMeta

        # Persistence attributes
        # FIXME Should these be present as part of Entities, or a separate Model?
        assert hasattr(Person.meta_, "abstract")
        assert hasattr(Person.meta_, "schema_name")
        assert hasattr(Person.meta_, "provider")

        # Fields Meta Info
        assert hasattr(Person.meta_, "declared_fields")
        assert hasattr(Person.meta_, "attributes")
        assert hasattr(Person.meta_, "id_field")

        # Domain attributes
        assert hasattr(Person.meta_, "aggregate_cls")
        assert hasattr(Person.meta_, "bounded_context")

    def test_entity_meta_has_declared_fields_on_construction(self):
        assert Person.meta_.declared_fields is not None
        assert all(
            key in Person.meta_.declared_fields.keys()
            for key in ["age", "first_name", "id", "last_name"]
        )

    def test_entity_declared_fields_hold_correct_field_types(self):
        assert type(Person.meta_.declared_fields["first_name"]) is String
        assert type(Person.meta_.declared_fields["last_name"]) is String
        assert type(Person.meta_.declared_fields["age"]) is Integer
        assert type(Person.meta_.declared_fields["id"]) is Auto

    def test_default_and_overridden_abstract_flag_in_meta(self):
        assert getattr(Person.meta_, "abstract") is False
        assert getattr(AbstractPerson.meta_, "abstract") is True

    def test_abstract_can_be_overridden_from_entity_abstract_class(self):
        """Test that `abstract` flag can be overridden"""

        assert hasattr(ConcretePerson.meta_, "abstract")
        assert getattr(ConcretePerson.meta_, "abstract") is False

    def test_abstract_can_be_overridden_from_entity_concrete_class(self):
        """Test that `abstract` flag can be overridden"""

        assert hasattr(AdultAbstractPerson.meta_, "abstract")
        assert getattr(AdultAbstractPerson.meta_, "abstract") is True

    def test_default_and_overridden_schema_name_in_meta(self):
        assert getattr(Person.meta_, "schema_name") == "person"
        assert getattr(DbPerson.meta_, "schema_name") == "pepes"

    def test_schema_name_can_be_overridden_in_entity_subclass(self):
        """Test that `schema_name` can be overridden"""
        assert hasattr(SqlPerson.meta_, "schema_name")
        assert getattr(SqlPerson.meta_, "schema_name") == "people"

    def test_default_and_overridden_provider_in_meta(self):
        assert getattr(Person.meta_, "provider") == "default"
        assert getattr(DifferentDbPerson.meta_, "provider") == "non-default"

    def test_provider_can_be_overridden_in_entity_subclass(self):
        """Test that `provider` can be overridden"""
        assert hasattr(SqlDifferentDbPerson.meta_, "provider")
        assert getattr(SqlDifferentDbPerson.meta_, "provider") == "non-default-sql"

    def test_default_and_overridden_order_by_in_meta(self):
        assert getattr(Person.meta_, "order_by") == ()
        assert getattr(OrderedPerson.meta_, "order_by") == ("first_name",)

    def test_order_by_can_be_overridden_in_entity_subclass(self):
        """Test that `order_by` can be overridden"""
        assert hasattr(OrderedPersonSubclass.meta_, "order_by")
        assert getattr(OrderedPersonSubclass.meta_, "order_by") == ("last_name",)

    def test_that_schema_is_not_inherited(self):
        assert Person.meta_.schema_name != Adult.meta_.schema_name
