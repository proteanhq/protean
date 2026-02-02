import pytest

from protean.fields import Auto, Integer, String
from protean.utils.container import Options
from protean.utils.reflection import attributes, declared_fields

from .elements import (
    AbstractPerson,
    Account,
    Adult,
    ConcretePerson,
    DbPerson,
    Person,
    PersonAutoSSN,
    Relative,
    SqlPerson,
)


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Account)
    test_domain.register(AbstractPerson, abstract=True)
    test_domain.register(ConcretePerson, part_of=Account)
    test_domain.register(Person, part_of=Account)
    test_domain.register(PersonAutoSSN, part_of=Account)
    test_domain.register(Relative, part_of=Account)
    test_domain.register(SqlPerson, part_of=Account, schema_name="people")
    test_domain.register(DbPerson, part_of=Account, schema_name="pepes")
    test_domain.register(Adult, part_of=Account, schema_name="adults")
    test_domain.init(traverse=False)


class TestEntityMeta:
    def test_entity_meta_structure(self):
        assert hasattr(Person, "meta_")
        assert type(Person.meta_) is Options

        # Persistence attributes
        assert hasattr(Person.meta_, "abstract")
        assert hasattr(Person.meta_, "schema_name")
        assert hasattr(Person.meta_, "provider")

        # Domain attributes
        assert hasattr(Person.meta_, "part_of")

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

    def test_default_and_overridden_abstract_flags(self):
        # Entity is not abstract by default
        assert getattr(Person.meta_, "abstract") is False

        # Entity can be marked explicitly as abstract
        assert getattr(AbstractPerson.meta_, "abstract") is True

        # Derived Entity is not abstract by default
        assert hasattr(ConcretePerson.meta_, "abstract")
        assert getattr(ConcretePerson.meta_, "abstract") is False

    def test_default_and_overridden_schema_name_in_meta(self):
        # Default
        assert getattr(Person.meta_, "schema_name") == "person"
        assert getattr(DbPerson.meta_, "schema_name") == "pepes"

    def test_schema_name_can_be_overridden_in_entity_subclass(self):
        """Test that `schema_name` can be overridden"""
        assert hasattr(SqlPerson.meta_, "schema_name")
        assert getattr(SqlPerson.meta_, "schema_name") == "people"

    def test_that_schema_is_not_inherited(self):
        assert Person.meta_.schema_name != Adult.meta_.schema_name

    def test_entity_meta_has_attributes_on_construction(self):
        assert list(attributes(Person).keys()) == [
            "first_name",
            "last_name",
            "age",
            "id",
            "account_id",
        ]
        assert list(attributes(PersonAutoSSN).keys()) == [
            "ssn",
            "first_name",
            "last_name",
            "age",
            "account_id",
        ]
        assert list(attributes(Relative).keys()) == [
            "first_name",
            "last_name",
            "age",
            "id",
            "account_id",
        ]  # `relative_of` is ignored

    def test_meta_equality(self):
        assert Person.meta_ != PersonAutoSSN.meta_
