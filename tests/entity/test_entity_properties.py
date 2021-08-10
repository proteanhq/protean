from uuid import UUID, uuid4

import pytest

from protean.core.field.basic import Auto, String
from protean.exceptions import InvalidOperationError, ValidationError

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
        assert hasattr(Person.meta_, "id_field")
        assert type(Person.meta_.id_field) is Auto

    def test_default_id_field_construction(self):
        assert "id" in Person.meta_.declared_fields
        assert "id" in Person.meta_.attributes

        assert type(Person.meta_.declared_fields["id"]) is Auto
        assert Person.meta_.id_field == Person.meta_.declared_fields["id"]

    def test_non_default_auto_id_field_construction(self):
        assert "id" not in PersonAutoSSN.meta_.declared_fields
        assert "id" not in PersonAutoSSN.meta_.attributes

        assert type(PersonAutoSSN.meta_.declared_fields["ssn"]) is Auto
        assert PersonAutoSSN.meta_.id_field.field_name == "ssn"
        assert (
            PersonAutoSSN.meta_.id_field == PersonAutoSSN.meta_.declared_fields["ssn"]
        )

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
