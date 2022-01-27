from uuid import UUID, uuid4

import pytest

from protean.exceptions import InvalidOperationError, ValidationError
from protean.fields import Auto, String
from protean.reflection import _ID_FIELD_NAME, attributes, declared_fields, id_field

from .elements import Adult, NotAPerson, Person, PersonAutoSSN, PersonExplicitID


class TestProperties:
    def test_conversion_of_aggregate_values_to_dict(self):
        person = Person(id=12, first_name="John", last_name="Doe")
        assert person.to_dict() == {
            "id": 12,
            "first_name": "John",
            "last_name": "Doe",
            "age": 21,
        }

    def test_repr_output_of_aggregate(self):
        person = Person(id=12, first_name="John")

        assert str(person) == "Person object (id: 12)"
        assert repr(person) == "<Person: Person object (id: 12)>"


class TestIdentity:
    """Grouping of Identity related test cases"""

    def test_id_field_in_meta(self):
        assert hasattr(Person, _ID_FIELD_NAME)
        assert type(id_field(Person)) is Auto

    def test_default_id_field_construction(self):
        assert "id" in declared_fields(Person)
        assert "id" in attributes(Person)

        assert type(declared_fields(Person)["id"]) is Auto
        assert id_field(Person) == declared_fields(Person)["id"]

    def test_non_default_auto_id_field_construction(self):
        assert "id" not in declared_fields(PersonAutoSSN)
        assert "id" not in attributes(PersonAutoSSN)

        assert type(declared_fields(PersonAutoSSN)["ssn"]) is Auto
        assert id_field(PersonAutoSSN).field_name == "ssn"
        assert id_field(PersonAutoSSN) == declared_fields(PersonAutoSSN)["ssn"]

    def test_non_default_explicit_id_field_construction(self, test_domain):
        assert "id" not in declared_fields(PersonExplicitID)
        assert "id" not in attributes(PersonExplicitID)

        assert type(declared_fields(PersonExplicitID)["ssn"]) is String
        assert id_field(PersonExplicitID).field_name == "ssn"
        assert id_field(PersonExplicitID) == declared_fields(PersonExplicitID)["ssn"]


class TestIdentityValues:
    """Grouping of Identity value related test cases"""

    def test_default_id_field_value(self):
        person = Person(first_name="John", last_name="Doe")
        assert person.id is not None

        try:
            uuid_obj = UUID(str(person.id))
        except ValueError:
            pytest.fail("ID is not valid UUID")

        assert str(uuid_obj) == person.id

    def test_that_ids_are_immutable(self):
        """Test that `id` cannot be changed once assigned"""
        person = Person(first_name="John", last_name="Doe")

        with pytest.raises(InvalidOperationError):
            person.id = 13

    def test_non_default_auto_id_field_value(self):
        person = PersonAutoSSN(first_name="John", last_name="Doe")
        assert person.ssn is not None

        try:
            uuid_obj = UUID(str(person.ssn))
        except ValueError:
            pytest.fail("SSN is not valid UUID")

        assert str(uuid_obj) == person.ssn

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
