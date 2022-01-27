from protean.container import Options
from protean.fields import Auto, Integer, String
from protean.reflection import attributes, declared_fields

from .elements import (
    AbstractPerson,
    Adult,
    ConcretePerson,
    DbPerson,
    DifferentDbPerson,
    Person,
    PersonAutoSSN,
    Relative,
    SqlDifferentDbPerson,
    SqlPerson,
)


class TestOptions:
    def test_entity_meta_structure(self):
        assert hasattr(Person, "meta_")
        assert type(Person.meta_) is Options

        # Persistence attributes
        # FIXME Should these be present as part of Entities, or a separate Model?
        assert hasattr(Person.meta_, "abstract")
        assert hasattr(Person.meta_, "schema_name")
        assert hasattr(Person.meta_, "provider")

        # Domain attributes
        assert hasattr(Person.meta_, "aggregate_cls")

    def test_entity_meta_has_declared_fields_on_construction(self):
        assert declared_fields(Person) is not None
        assert all(
            key in declared_fields(Person).keys()
            for key in ["age", "first_name", "id", "last_name"]
        )

    def test_entity_declared_fields_hold_correct_field_types(self):
        assert type(declared_fields(Person)["first_name"]) is String
        assert type(declared_fields(Person)["last_name"]) is String
        assert type(declared_fields(Person)["age"]) is Integer
        assert type(declared_fields(Person)["id"]) is Auto

    def test_default_and_overridden_abstract_flag_in_meta(self):
        assert getattr(Person.meta_, "abstract") is False
        assert getattr(AbstractPerson.meta_, "abstract") is True

    def test_abstract_can_be_overridden_from_entity_abstract_class(self):
        """Test that `abstract` flag can be overridden"""

        assert hasattr(ConcretePerson.meta_, "abstract")
        assert getattr(ConcretePerson.meta_, "abstract") is False

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

    def test_that_schema_is_not_inherited(self):
        assert Person.meta_.schema_name != Adult.meta_.schema_name

    def test_entity_meta_has_attributes_on_construction(self):
        assert list(attributes(Person).keys()) == [
            "first_name",
            "last_name",
            "age",
            "id",
        ]
        assert list(attributes(PersonAutoSSN).keys()) == [
            "ssn",
            "first_name",
            "last_name",
            "age",
        ]
        assert list(attributes(Relative).keys()) == [
            "first_name",
            "last_name",
            "age",
            "id",
        ]  # `relative_of` is ignored
