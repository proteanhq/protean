from collections import defaultdict
from enum import Enum

from protean.core.entity import BaseEntity, EntityMeta
from protean.core.field.association import HasOne
from protean.core.field.basic import Auto, Integer, String


class AbstractPerson(BaseEntity):
    age = Integer(default=5)

    class Meta:
        abstract = True


class ConcretePerson(BaseEntity):
    first_name = String(max_length=50, required=True)
    last_name = String(max_length=50)


class AdultAbstractPerson(ConcretePerson):
    age = Integer(default=21)

    class Meta:
        abstract = True


class Person(BaseEntity):
    first_name = String(max_length=50, required=True)
    last_name = String(max_length=50)
    age = Integer(default=21)


class PersonAutoSSN(BaseEntity):
    ssn = Auto(identifier=True)
    first_name = String(max_length=50, required=True)
    last_name = String(max_length=50)
    age = Integer(default=21)


class PersonExplicitID(BaseEntity):
    ssn = String(max_length=36, identifier=True)
    first_name = String(max_length=50, required=True)
    last_name = String(max_length=50)
    age = Integer(default=21)


class Relative(BaseEntity):
    first_name = String(max_length=50, required=True)
    last_name = String(max_length=50)
    age = Integer(default=21)
    relative_of = HasOne(Person)


class Adult(Person):
    class Meta:
        schema_name = "adults"


class NotAPerson(BaseEntity):
    first_name = String(max_length=50, required=True)
    last_name = String(max_length=50)
    age = Integer(default=21)


# Entities to test Meta Info overriding # START #
class DbPerson(BaseEntity):
    first_name = String(max_length=50, required=True)
    last_name = String(max_length=50)
    age = Integer(default=21)

    class Meta:
        schema_name = "pepes"


class SqlPerson(Person):
    class Meta:
        schema_name = "people"


class DifferentDbPerson(Person):
    class Meta:
        provider = "non-default"


class SqlDifferentDbPerson(Person):
    class Meta:
        provider = "non-default-sql"


class OrderedPerson(BaseEntity):
    first_name = String(max_length=50, required=True)
    last_name = String(max_length=50)
    age = Integer(default=21)

    class Meta:
        order_by = "first_name"


class OrderedPersonSubclass(Person):
    class Meta:
        order_by = "last_name"


class BuildingStatus(Enum):
    WIP = "WIP"
    DONE = "DONE"


class Building(BaseEntity):
    name = String(max_length=50)
    floors = Integer()
    status = String(choices=BuildingStatus)

    def defaults(self):
        if not self.status:
            if self.floors == 4:
                self.status = BuildingStatus.DONE.value
            else:
                self.status = BuildingStatus.WIP.value

    def clean(self):
        errors = defaultdict(list)

        if self.floors >= 4 and self.status != BuildingStatus.DONE.value:
            errors["status"].append("should be DONE")

        return errors


class TestEntityMeta:
    def test_entity_meta_structure(self):
        assert hasattr(Person, "meta_")
        assert type(Person.meta_) is EntityMeta

        # Persistence attributes
        assert hasattr(Person.meta_, "abstract")
        assert hasattr(Person.meta_, "schema_name")
        assert hasattr(Person.meta_, "provider")

        # Fields Meta Info
        assert hasattr(Person.meta_, "declared_fields")
        assert hasattr(Person.meta_, "attributes")
        assert hasattr(Person.meta_, "id_field")

        # Domain attributes
        assert hasattr(Person.meta_, "aggregate_cls")

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

    def test_default_and_overridden_abstract_flags(self):
        # Entity is not abstract by default
        assert getattr(Person.meta_, "abstract") is False

        # Entity can be marked explicitly as abstract
        assert getattr(AbstractPerson.meta_, "abstract") is True

        # Derived Entity is not abstract by default
        assert getattr(ConcretePerson.meta_, "abstract") is False

        # Entity can be marked abstract at any level of inheritance
        assert getattr(AdultAbstractPerson.meta_, "abstract") is True

    def test_default_and_overridden_schema_name_in_meta(self):
        # Default
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

    def test_entity_meta_has_mandatory_fields_on_construction(self):
        assert hasattr(Person.meta_, "mandatory_fields")
        assert list(Person.meta_.mandatory_fields.keys()) == ["first_name"]
        assert list(PersonAutoSSN.meta_.mandatory_fields.keys()) == ["first_name"]
        assert list(PersonExplicitID.meta_.mandatory_fields.keys()) == [
            "ssn",
            "first_name",
        ]

    def test_entity_meta_has_attributes_on_construction(self):
        assert hasattr(Person.meta_, "mandatory_fields")
        assert list(Person.meta_.attributes.keys()) == [
            "first_name",
            "last_name",
            "age",
            "id",
        ]
        assert list(PersonAutoSSN.meta_.attributes.keys()) == [
            "ssn",
            "first_name",
            "last_name",
            "age",
        ]
        assert list(Relative.meta_.attributes.keys()) == [
            "first_name",
            "last_name",
            "age",
            "id",
        ]  # `relative_of` is ignored
