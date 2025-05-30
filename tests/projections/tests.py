from collections import defaultdict
from enum import Enum
from uuid import uuid4

import pytest

from protean.core.projection import BaseProjection
from protean.exceptions import (
    IncorrectUsageError,
    InvalidOperationError,
    NotSupportedError,
    ValidationError,
)
from protean.fields import Auto, Identifier, Integer, String
from protean.utils import fully_qualified_name
from protean.utils.container import Options
from protean.utils.reflection import (
    _ID_FIELD_NAME,
    attributes,
    declared_fields,
    id_field,
)


class AbstractPerson(BaseProjection):
    age = Integer(default=5)


class ConcretePerson(BaseProjection):
    person_id = Identifier(identifier=True)
    first_name = String(max_length=50, required=True)
    last_name = String(max_length=50)


class Person(BaseProjection):
    person_id = Identifier(identifier=True)
    first_name = String(max_length=50, required=True)
    last_name = String(max_length=50)
    age = Integer(default=21)


class PersonAutoSSN(BaseProjection):
    ssn = Auto(identifier=True)
    first_name = String(max_length=50, required=True)
    last_name = String(max_length=50)
    age = Integer(default=21)


class PersonExplicitID(BaseProjection):
    ssn = String(max_length=36, identifier=True)
    first_name = String(max_length=50, required=True)
    last_name = String(max_length=50)
    age = Integer(default=21)


class PersonWithoutIdField(BaseProjection):
    first_name = String(max_length=50, required=True)
    last_name = String(max_length=50)
    age = Integer(default=21)


class Adult(Person):
    pass


class NotAPerson(BaseProjection):
    identifier = Identifier(identifier=True)
    first_name = String(max_length=50, required=True)
    last_name = String(max_length=50)
    age = Integer(default=21)


# Entities to test Meta Info overriding # START #
class DbPerson(BaseProjection):
    person_id = Identifier(identifier=True)
    first_name = String(max_length=50, required=True)
    last_name = String(max_length=50)
    age = Integer(default=21)


class SqlPerson(Person):
    pass


class DifferentDbPerson(Person):
    pass


class SqlDifferentDbPerson(Person):
    pass


class OrderedPerson(BaseProjection):
    person_id = Identifier(identifier=True)
    first_name = String(max_length=50, required=True)
    last_name = String(max_length=50)
    age = Integer(default=21)


class OrderedPersonSubclass(Person):
    pass


class BuildingStatus(Enum):
    WIP = "WIP"
    DONE = "DONE"


class Building(BaseProjection):
    building_id = Identifier(identifier=True)
    name = String(max_length=50)
    floors = Integer()
    status = String(choices=BuildingStatus)

    def defaults(self):
        if not self.status:
            if self.floors == 4:
                self.status = BuildingStatus.DONE.value
            else:
                self.status = BuildingStatus.WIP.value

    def _postcheck(self):
        errors = defaultdict(list)

        if self.floors >= 4 and self.status != BuildingStatus.DONE.value:
            errors["status"].append("should be DONE")

        return errors


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(AbstractPerson, abstract=True)
    test_domain.register(Person)
    test_domain.register(PersonAutoSSN)
    test_domain.register(PersonExplicitID)
    test_domain.register(Adult)
    test_domain.register(NotAPerson)
    test_domain.register(DbPerson, schema_name="peoples")
    test_domain.register(SqlPerson, schema_name="people")
    test_domain.register(DifferentDbPerson, provider="non-default")
    test_domain.register(SqlDifferentDbPerson, provider="non-default-sql")
    test_domain.register(OrderedPerson, order_by="first_name")
    test_domain.register(OrderedPersonSubclass, order_by="last_name")
    test_domain.register(Building)
    test_domain.init(traverse=False)


def test_projection_cannot_be_instantiated(test_domain):
    with pytest.raises(NotSupportedError) as excinfo:
        BaseProjection()

    assert "BaseProjection cannot be instantiated" in str(excinfo.value)


class TestProjectionRegistration:
    def test_manual_registration_of_projection(self, test_domain):
        class Comment(BaseProjection):
            comment_id = Identifier(identifier=True)
            content = String(max_length=500)

        test_domain.register(Comment)

        assert fully_qualified_name(Comment) in test_domain.registry.projections

    def test_setting_provider_in_decorator_based_registration(self, test_domain):
        @test_domain.projection
        class Comment:
            comment_id = Identifier(identifier=True)
            content = String(max_length=500)

        assert fully_qualified_name(Comment) in test_domain.registry.projections

    def test_id_field_mandatory_in_projections(self, test_domain):
        with pytest.raises(IncorrectUsageError) as excinfo:
            test_domain.register(PersonWithoutIdField)

        assert "needs to have at least one identifier" in str(excinfo.value)


class TestProperties:
    def test_conversion_of_projection_values_to_dict(self):
        person = Person(person_id=12, first_name="John", last_name="Doe")
        assert person.to_dict() == {
            "person_id": "12",
            "first_name": "John",
            "last_name": "Doe",
            "age": 21,
        }

    def test_repr_output_of_projection(self):
        person = Person(person_id=12, first_name="John")

        assert (
            str(person)
            == "Person object ({'person_id': '12', 'first_name': 'John', 'last_name': None, 'age': 21})"
        )
        assert (
            repr(person)
            == "<Person: Person object ({'person_id': '12', 'first_name': 'John', 'last_name': None, 'age': 21})>"
        )


class TestProjectionMeta:
    def test_projection_meta_attributes(self):
        assert hasattr(Person, "meta_")
        assert type(Person.meta_) is Options

        # Persistence attributes
        # FIXME Should these be present as part of Projections, or a separate Model?
        assert hasattr(Person.meta_, "abstract")
        assert hasattr(Person.meta_, "schema_name")
        assert hasattr(Person.meta_, "provider")
        assert hasattr(Person.meta_, "cache")

        assert id_field(Person) is not None
        assert id_field(Person) == declared_fields(Person)["person_id"]

    def test_absence_of_entity_specific_attributes(self):
        assert hasattr(Person.meta_, "part_of") is False

    def test_projection_meta_has_declared_fields_on_construction(self):
        assert declared_fields(Person) is not None
        assert all(
            key in declared_fields(Person).keys()
            for key in ["age", "first_name", "person_id", "last_name"]
        )

    def test_projection_declared_fields_hold_correct_field_types(self):
        assert type(declared_fields(Person)["first_name"]) is String
        assert type(declared_fields(Person)["last_name"]) is String
        assert type(declared_fields(Person)["age"]) is Integer
        assert type(declared_fields(Person)["person_id"]) is Identifier

    def test_default_and_overridden_abstract_flag_in_meta(self):
        assert getattr(Person.meta_, "abstract") is False
        assert getattr(AbstractPerson.meta_, "abstract") is True

    def test_abstract_can_be_overridden_from_projection_abstract_class(self):
        """Test that `abstract` flag can be overridden"""

        assert hasattr(ConcretePerson.meta_, "abstract")
        assert getattr(ConcretePerson.meta_, "abstract") is False

    def test_default_and_overridden_schema_name_in_meta(self):
        assert getattr(Person.meta_, "schema_name") == "person"
        assert getattr(DbPerson.meta_, "schema_name") == "peoples"

    def test_schema_name_can_be_overridden_in_projection_subclass(self):
        """Test that `schema_name` can be overridden"""
        assert hasattr(SqlPerson.meta_, "schema_name")
        assert getattr(SqlPerson.meta_, "schema_name") == "people"

    def test_default_and_overridden_provider_in_meta(self):
        assert getattr(Person.meta_, "provider") == "default"
        assert getattr(DifferentDbPerson.meta_, "provider") == "non-default"

    def test_provider_can_be_overridden_in_projection_subclass(self):
        """Test that `provider` can be overridden"""
        assert hasattr(SqlDifferentDbPerson.meta_, "provider")
        assert getattr(SqlDifferentDbPerson.meta_, "provider") == "non-default-sql"

    def test_default_and_overridden_order_by_in_meta(self):
        assert getattr(Person.meta_, "order_by") == ()
        assert getattr(OrderedPerson.meta_, "order_by") == "first_name"

    def test_order_by_can_be_overridden_in_projection_subclass(self):
        """Test that `order_by` can be overridden"""
        assert hasattr(OrderedPersonSubclass.meta_, "order_by")
        assert getattr(OrderedPersonSubclass.meta_, "order_by") == "last_name"

    def test_that_schema_is_not_inherited(self):
        assert Person.meta_.schema_name != Adult.meta_.schema_name

    def test_error_when_neither_database_nor_cache_provider_is_specified(
        self, test_domain
    ):
        with pytest.raises(NotSupportedError):

            class PersonWithNoDatabaseAndCache(BaseProjection):
                person_id = Identifier(identifier=True)
                first_name = String(max_length=50, required=True)
                last_name = String(max_length=50)
                age = Integer(default=21)

            test_domain.register(
                PersonWithNoDatabaseAndCache, provider=None, cache=None
            )

    def test_that_specifying_cache_overrides_database_provider(self, test_domain):
        class PersonWithCache(BaseProjection):
            person_id = Identifier(identifier=True)
            first_name = String(max_length=50, required=True)
            last_name = String(max_length=50)
            age = Integer(default=21)

        test_domain.register(PersonWithCache, cache="default")

        assert PersonWithCache.meta_.provider is None


class TestIdentity:
    """Grouping of Identity related test cases"""

    def test_id_field_in_meta(self):
        assert hasattr(Person, _ID_FIELD_NAME)
        assert id_field(Person) is not None
        assert id_field(Person) == declared_fields(Person)["person_id"]

        assert type(id_field(Person)) is Identifier
        declared_fields(Person)["person_id"].identifier is True

    def test_id_field_recognition(self):
        assert "person_id" in declared_fields(Person)
        assert "person_id" in attributes(Person)

        assert type(declared_fields(Person)["person_id"]) is Identifier
        assert id_field(Person) == declared_fields(Person)["person_id"]
        declared_fields(Person)["person_id"].identifier is True

    def test_non_default_auto_id_field_construction(self):
        assert "id" not in declared_fields(PersonAutoSSN)
        assert "id" not in attributes(PersonAutoSSN)

        assert type(declared_fields(PersonAutoSSN)["ssn"]) is Auto
        assert id_field(PersonAutoSSN).field_name == "ssn"
        assert id_field(PersonAutoSSN) == declared_fields(PersonAutoSSN)["ssn"]
        declared_fields(PersonAutoSSN)["ssn"].identifier is True

    def test_non_default_explicit_id_field_construction(self, test_domain):
        assert "id" not in declared_fields(PersonExplicitID)
        assert "id" not in attributes(PersonExplicitID)

        assert type(declared_fields(PersonExplicitID)["ssn"]) is String
        assert id_field(PersonExplicitID).field_name == "ssn"
        assert id_field(PersonExplicitID) == declared_fields(PersonExplicitID)["ssn"]

    def test_id_field_not_required_for_abstract_projections(self):
        assert id_field(AbstractPerson) is None


class TestIdentityValues:
    """Grouping of Identity value related test cases"""

    def test_mandatory_nature_of_id_field_value(self):
        with pytest.raises(ValidationError):
            Person(first_name="John", last_name="Doe")

    def test_assigning_explicit_id_during_initialization(self):
        person = Person(person_id=uuid4(), first_name="John", last_name="Doe")
        assert person.person_id is not None

    def test_that_ids_are_immutable(self):
        """Test that `id` cannot be changed once assigned"""
        person = Person(person_id=uuid4(), first_name="John", last_name="Doe")

        with pytest.raises(InvalidOperationError):
            person.person_id = 13

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

    def test_that_abstract_projections_can_be_instantiated_without_id_field(self):
        with pytest.raises(NotSupportedError) as excinfo:
            AbstractPerson(first_name="John", last_name="Doe")

        assert (
            "AbstractPerson class has been marked abstract and cannot be instantiated"
            in str(excinfo.value)
        )


class TestEquivalence:
    def test_that_two_entities_with_same_id_are_treated_as_equal(self):
        person1 = Person(person_id=12345, first_name="John", last_name="Doe")
        person2 = Person(person_id=12346, first_name="John", last_name="Doe")

        assert person1 != person2  # Because their identities are different
        assert person2 != person1  # Because their identities are different

        person3 = Person(person_id=12345, first_name="John", last_name="Doe")
        assert (
            person1 == person3
        )  # Because it's the same record even though attributes differ
        assert person3 == person1

    def test_that_two_entities_of_different_types_are_different_even_with_same_id(self):
        """Test that two entities are not considered equal even if they have the same ID
        and one belongs to a different Entity class
        """
        not_a_person = NotAPerson(identifier=12345, first_name="John", last_name="Doe")
        person = Person(person_id=12345, first_name="John", last_name="Doe")

        assert not_a_person != person  # Even though their identities are the same
        assert person != not_a_person  # Even though their identities are the same

    def test_that_two_entities_of_inherited_types_are_different_even_with_same_id(self):
        """Test that two entities are not considered equal even if they have the same ID
        and one is subclassed from the other
        """
        adult = Adult(person_id=12345, first_name="John", last_name="Doe")
        person = Person(person_id=12345, first_name="John", last_name="Doe")

        assert adult != person  # Even though their identities are the same
        assert person != adult  # Even though their identities are the same

    def test_generated_aggregate_hash(self):
        """Test that the entity's hash is based on its identity"""
        hashed_id = hash("12345")

        person = Person(person_id=12345, first_name="John", last_name="Doe")
        assert hashed_id == hash(
            person
        )  # FIXME Should hash be based on ID alone, or other attrs too?

    def test_that_two_aggregates_that_are_equal_have_equal_hash(self):
        person1 = Person(person_id=12345, first_name="John", last_name="Doe")
        person2 = Person(person_id=12345, first_name="John", last_name="Doe")

        assert hash(person1) == hash(person2)


class TestProjectionState:
    def test_that_projections_have_state(self):
        person = Person(person_id=12, first_name="John", last_name="Doe")
        assert person.state_ is not None
        assert person.state_.is_new is True
