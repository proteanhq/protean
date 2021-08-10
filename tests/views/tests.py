from collections import defaultdict
from enum import Enum
from uuid import UUID, uuid4

import pytest

from protean.core.field.basic import Auto, Identifier, Integer, String
from protean.core.view import BaseView, ViewMeta
from protean.exceptions import InvalidOperationError, ValidationError
from protean.utils import fully_qualified_name


class AbstractPerson(BaseView):
    age = Integer(default=5)

    class Meta:
        abstract = True


class ConcretePerson(BaseView):
    first_name = String(max_length=50, required=True)
    last_name = String(max_length=50)


class AdultAbstractPerson(ConcretePerson):
    age = Integer(default=21)

    class Meta:
        abstract = True


class Person(BaseView):
    first_name = String(max_length=50, required=True)
    last_name = String(max_length=50)
    age = Integer(default=21)


class PersonAutoSSN(BaseView):
    ssn = Auto(identifier=True)
    first_name = String(max_length=50, required=True)
    last_name = String(max_length=50)
    age = Integer(default=21)


class PersonExplicitID(BaseView):
    ssn = String(max_length=36, identifier=True)
    first_name = String(max_length=50, required=True)
    last_name = String(max_length=50)
    age = Integer(default=21)


class Adult(Person):
    pass

    class Meta:
        schema_name = "adults"


class NotAPerson(BaseView):
    first_name = String(max_length=50, required=True)
    last_name = String(max_length=50)
    age = Integer(default=21)


# Entities to test Meta Info overriding # START #
class DbPerson(BaseView):
    first_name = String(max_length=50, required=True)
    last_name = String(max_length=50)
    age = Integer(default=21)

    class Meta:
        schema_name = "peoples"


class SqlPerson(Person):
    class Meta:
        schema_name = "people"


class DifferentDbPerson(Person):
    class Meta:
        provider = "non-default"


class SqlDifferentDbPerson(Person):
    class Meta:
        provider = "non-default-sql"


class OrderedPerson(BaseView):
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


class Building(BaseView):
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


class TestViewRegistration:
    def test_manual_registration_of_view(self, test_domain):
        class Comment(BaseView):
            content = String(max_length=500)

        test_domain.register(Comment)

        assert fully_qualified_name(Comment) in test_domain.registry.views

    def test_setting_provider_in_decorator_based_registration(self, test_domain):
        @test_domain.view
        class Comment(BaseView):
            content = String(max_length=500)

        assert fully_qualified_name(Comment) in test_domain.registry.views


class TestProperties:
    def test_conversion_of_view_values_to_dict(self):
        person = Person(id=12, first_name="John", last_name="Doe")
        assert person.to_dict() == {
            "id": 12,
            "first_name": "John",
            "last_name": "Doe",
            "age": 21,
        }

    def test_repr_output_of_view(self):
        person = Person(id=12, first_name="John")

        assert str(person) == "Person object (id: 12)"
        assert repr(person) == "<Person: Person object (id: 12)>"


class TestViewMeta:
    def test_view_meta_attributes(self):
        assert hasattr(Person, "meta_")
        assert type(Person.meta_) is ViewMeta

        # Persistence attributes
        # FIXME Should these be present as part of Views, or a separate Model?
        assert hasattr(Person.meta_, "abstract")
        assert hasattr(Person.meta_, "schema_name")
        assert hasattr(Person.meta_, "provider")
        assert hasattr(Person.meta_, "cache")

        # Fields Meta Info
        assert hasattr(Person.meta_, "declared_fields")
        assert hasattr(Person.meta_, "attributes")
        assert hasattr(Person.meta_, "id_field")

    def test_absence_of_entity_specific_attributes(self):
        assert hasattr(Person.meta_, "aggregate_cls") is False

    def test_view_meta_has_declared_fields_on_construction(self):
        assert Person.meta_.declared_fields is not None
        assert all(
            key in Person.meta_.declared_fields.keys()
            for key in ["age", "first_name", "id", "last_name"]
        )

    def test_view_declared_fields_hold_correct_field_types(self):
        assert type(Person.meta_.declared_fields["first_name"]) is String
        assert type(Person.meta_.declared_fields["last_name"]) is String
        assert type(Person.meta_.declared_fields["age"]) is Integer
        assert type(Person.meta_.declared_fields["id"]) is Identifier

    def test_default_and_overridden_abstract_flag_in_meta(self):
        assert getattr(Person.meta_, "abstract") is False
        assert getattr(AbstractPerson.meta_, "abstract") is True

    def test_abstract_can_be_overridden_from_view_abstract_class(self):
        """Test that `abstract` flag can be overridden"""

        assert hasattr(ConcretePerson.meta_, "abstract")
        assert getattr(ConcretePerson.meta_, "abstract") is False

    def test_abstract_can_be_overridden_from_view_concrete_class(self):
        """Test that `abstract` flag can be overridden"""

        assert hasattr(AdultAbstractPerson.meta_, "abstract")
        assert getattr(AdultAbstractPerson.meta_, "abstract") is True

    def test_default_and_overridden_schema_name_in_meta(self):
        assert getattr(Person.meta_, "schema_name") == "person"
        assert getattr(DbPerson.meta_, "schema_name") == "peoples"

    def test_schema_name_can_be_overridden_in_view_subclass(self):
        """Test that `schema_name` can be overridden"""
        assert hasattr(SqlPerson.meta_, "schema_name")
        assert getattr(SqlPerson.meta_, "schema_name") == "people"

    def test_default_and_overridden_provider_in_meta(self):
        assert getattr(Person.meta_, "provider") == "default"
        assert getattr(DifferentDbPerson.meta_, "provider") == "non-default"

    def test_provider_can_be_overridden_in_view_subclass(self):
        """Test that `provider` can be overridden"""
        assert hasattr(SqlDifferentDbPerson.meta_, "provider")
        assert getattr(SqlDifferentDbPerson.meta_, "provider") == "non-default-sql"

    def test_default_and_overridden_order_by_in_meta(self):
        assert getattr(Person.meta_, "order_by") == ()
        assert getattr(OrderedPerson.meta_, "order_by") == ("first_name",)

    def test_order_by_can_be_overridden_in_view_subclass(self):
        """Test that `order_by` can be overridden"""
        assert hasattr(OrderedPersonSubclass.meta_, "order_by")
        assert getattr(OrderedPersonSubclass.meta_, "order_by") == ("last_name",)

    def test_that_schema_is_not_inherited(self):
        assert Person.meta_.schema_name != Adult.meta_.schema_name


class TestIdentity:
    """Grouping of Identity related test cases"""

    def test_id_field_in_meta(self):
        assert hasattr(Person.meta_, "id_field")
        assert type(Person.meta_.id_field) is Identifier
        Person.meta_.declared_fields["id"].identifier is True

    def test_default_id_field_construction(self):
        assert "id" in Person.meta_.declared_fields
        assert "id" in Person.meta_.attributes

        assert type(Person.meta_.declared_fields["id"]) is Identifier
        assert Person.meta_.id_field == Person.meta_.declared_fields["id"]
        Person.meta_.declared_fields["id"].identifier is True

    def test_non_default_auto_id_field_construction(self):
        assert "id" not in PersonAutoSSN.meta_.declared_fields
        assert "id" not in PersonAutoSSN.meta_.attributes

        assert type(PersonAutoSSN.meta_.declared_fields["ssn"]) is Auto
        assert PersonAutoSSN.meta_.id_field.field_name == "ssn"
        assert (
            PersonAutoSSN.meta_.id_field == PersonAutoSSN.meta_.declared_fields["ssn"]
        )
        PersonAutoSSN.meta_.declared_fields["ssn"].identifier is True

    def test_non_default_explicit_id_field_construction(self, test_domain):
        assert "id" not in PersonExplicitID.meta_.declared_fields
        assert "id" not in PersonExplicitID.meta_.attributes

        assert type(PersonExplicitID.meta_.declared_fields["ssn"]) is String
        assert PersonExplicitID.meta_.id_field.field_name == "ssn"
        assert (
            PersonExplicitID.meta_.id_field
            == PersonExplicitID.meta_.declared_fields["ssn"]
        )


class TestIdentityValues:
    """Grouping of Identity value related test cases"""

    def test_mandatory_nature_of_id_field_value(self):
        with pytest.raises(ValidationError):
            Person(first_name="John", last_name="Doe")

    def test_assigning_explicit_id_during_initialization(self):
        person = Person(id=uuid4(), first_name="John", last_name="Doe")
        assert person.id is not None

    def test_that_ids_are_immutable(self):
        """Test that `id` cannot be changed once assigned"""
        person = Person(id=uuid4(), first_name="John", last_name="Doe")

        with pytest.raises(InvalidOperationError):
            person.id = 13

    def test_non_default_auto_id_field_value(self):
        person = PersonAutoSSN(first_name="John", last_name="Doe")
        assert person.ssn is not None

        uuid_obj = None
        try:
            uuid_obj = UUID(str(person.ssn))
        except ValueError:
            pytest.fail("SSN is not valid UUID")

        assert str(uuid_obj) == str(person.ssn)

    def test_non_default_explicit_id_field_value(self):
        with pytest.raises(ValidationError):
            PersonExplicitID(first_name="John Doe")

        new_uuid = uuid4()
        role = PersonExplicitID(ssn=new_uuid, first_name="John")
        assert role is not None
        assert role.ssn == str(new_uuid)

    def test_that_explicit_id_can_be_supplied_to_auto_id_field(self):
        new_uuid = uuid4()
        person = PersonExplicitID(ssn=new_uuid, first_name="John")
        assert person.ssn is not None
        assert person.ssn == str(new_uuid)


class TestEquivalence:
    def test_that_two_entities_with_same_id_are_treated_as_equal(self):
        person1 = Person(id=12345, first_name="John", last_name="Doe")
        person2 = Person(id=12346, first_name="John", last_name="Doe")

        assert person1 != person2  # Because their identities are different
        assert person2 != person1  # Because their identities are different

        person3 = Person(id=12345, first_name="John", last_name="Doe")
        assert (
            person1 == person3
        )  # Because it's the same record even though attributes differ
        assert person3 == person1

    def test_that_two_entities_of_different_types_are_different_even_with_same_id(self):
        """Test that two entities are not considered equal even if they have the same ID
            and one belongs to a different Entity class
        """
        not_a_person = NotAPerson(id=12345, first_name="John", last_name="Doe")
        person = Person(id=12345, first_name="John", last_name="Doe")

        assert not_a_person != person  # Even though their identities are the same
        assert person != not_a_person  # Even though their identities are the same

    def test_that_two_entities_of_inherited_types_are_different_even_with_same_id(self):
        """Test that two entities are not considered equal even if they have the same ID
            and one is subclassed from the other
        """
        adult = Adult(id=12345, first_name="John", last_name="Doe")
        person = Person(id=12345, first_name="John", last_name="Doe")

        assert adult != person  # Even though their identities are the same
        assert person != adult  # Even though their identities are the same

    def test_generated_aggregate_hash(self):
        """Test that the entity's hash is based on its identity"""
        hashed_id = hash(12345)

        person = Person(id=12345, first_name="John", last_name="Doe")
        assert hashed_id == hash(
            person
        )  # FIXME Should hash be based on ID alone, or other attrs too?

    def test_that_two_aggregates_that_are_equal_have_equal_hash(self):
        person1 = Person(id=12345, first_name="John", last_name="Doe")
        person2 = Person(id=12345, first_name="John", last_name="Doe")

        assert hash(person1) == hash(person2)
