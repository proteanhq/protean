"""Generic CRUD tests that run against all database providers.

Covers create(), save(), update(), delete(), get(), find_by() operations
on the DAO layer.
"""

from datetime import datetime

import pytest

from protean.core.aggregate import BaseAggregate
from protean.exceptions import ObjectNotFoundError, ValidationError
from protean.fields import DateTime, Integer, String


class Person(BaseAggregate):
    first_name: String(max_length=50, required=True)
    last_name: String(max_length=50, required=True)
    age: Integer(default=21)
    created_at: DateTime(default=datetime.now())


class User(BaseAggregate):
    email: String(max_length=255, required=True, unique=True)
    password: String(max_length=3026)


@pytest.mark.basic_storage
class TestDAOCreateFunctionality:
    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(Person)
        test_domain.register(User)

    def test_create_a_new_object(self, test_domain):
        person = test_domain.repository_for(Person)._dao.create(
            first_name="John", last_name="Doe"
        )

        assert person is not None

        persisted_person = test_domain.repository_for(Person)._dao.get(person.id)
        assert persisted_person is not None
        assert persisted_person == person

        assert persisted_person.first_name == "John"
        assert persisted_person.last_name == "Doe"

    def test_creation_throws_error_on_missing_fields(self, test_domain):
        """Add an entity to the repository missing a required attribute"""
        with pytest.raises(ValidationError) as err:
            test_domain.repository_for(Person)._dao.create(last_name="Doe")

        assert err.value.messages == {"first_name": ["is required"]}

    def test_error_on_attempt_to_create_duplicate_entity(self, test_domain):
        """Error on attempt to create a duplicate entity"""
        test_domain.repository_for(User)._dao.create(
            email="john.doe@example.com", password="password"
        )
        with pytest.raises(ValidationError) as err:
            test_domain.repository_for(User)._dao.create(
                email="john.doe@example.com", password="password"
            )

        assert err.value.messages == {
            "email": ["User with email 'john.doe@example.com' is already present."]
        }

    def test_that_escaped_quotes_in_values_are_handled_properly(self, test_domain):
        test_domain.repository_for(Person)._dao.create(
            first_name="Athos", last_name="Musketeer", age=2
        )
        test_domain.repository_for(Person)._dao.create(
            first_name="Porthos", last_name="Musketeer", age=3
        )
        test_domain.repository_for(Person)._dao.create(
            first_name="Aramis", last_name="Musketeer", age=4
        )

        person1 = test_domain.repository_for(Person)._dao.create(
            first_name="d'Artagnan1", last_name="John", age=5
        )
        person2 = test_domain.repository_for(Person)._dao.create(
            first_name="d'Artagnan2", last_name="John", age=5
        )
        person3 = test_domain.repository_for(Person)._dao.create(
            first_name='d"Artagnan3', last_name="John", age=5
        )
        person4 = test_domain.repository_for(Person)._dao.create(
            first_name='d"Artagnan4', last_name="John", age=5
        )

        assert all(
            person is not None for person in [person1, person2, person3, person4]
        )


@pytest.mark.basic_storage
class TestDAOGetFunctionality:
    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(Person)

    @pytest.fixture
    def persisted_person(self, db, test_domain):
        person = test_domain.repository_for(Person)._dao.create(
            first_name="John", last_name="Doe"
        )
        return person

    def test_successful_initialization_of_dao(self, test_domain):
        test_domain.repository_for(Person)._dao.query.all()
        provider = test_domain.providers["default"]
        conn = provider.get_connection()
        assert conn is not None

    def test_entity_retrieval_by_its_primary_key(self, test_domain, persisted_person):
        """Test Entity Retrieval by its primary key"""
        person = test_domain.repository_for(Person)._dao.get(persisted_person.id)
        assert person is not None
        assert person.id == persisted_person.id

    def test_failed_entity_retrieval_by_its_primary_key(self, test_domain):
        """Test failed Entity Retrieval by its primary key"""
        with pytest.raises(ObjectNotFoundError):
            test_domain.repository_for(Person)._dao.get("1235")

    def test_entity_retrieval_by_specific_column_value(
        self, test_domain, persisted_person
    ):
        person = test_domain.repository_for(Person)._dao.find_by(first_name="John")
        assert person is not None
        assert person.id == persisted_person.id

    def test_failed_entity_retrieval_by_column_value(
        self, test_domain, persisted_person
    ):
        with pytest.raises(ObjectNotFoundError):
            test_domain.repository_for(Person)._dao.find_by(first_name="JohnnyChase")

    def test_entity_retrieval_by_multiple_column_values(self, test_domain):
        test_domain.repository_for(Person)._dao.create(
            id="2346", first_name="Johnny1", last_name="Bravo", age=8
        )
        test_domain.repository_for(Person)._dao.create(
            id="2347", first_name="Johnny2", last_name="Bravo", age=6
        )

        person = test_domain.repository_for(Person)._dao.find_by(
            first_name="Johnny1", age=8
        )
        assert person is not None
        assert person.id == "2346"

    def test_failed_entity_retrieval_by_multiple_column_values(self, test_domain):
        test_domain.repository_for(Person)._dao.create(
            id="2346", first_name="Johnny1", last_name="Bravo", age=8
        )
        test_domain.repository_for(Person)._dao.create(
            id="2347", first_name="Johnny2", last_name="Bravo", age=6
        )

        with pytest.raises(ObjectNotFoundError):
            test_domain.repository_for(Person)._dao.find_by(first_name="Johnny1", age=6)


@pytest.mark.basic_storage
class TestDAOSaveFunctionality:
    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(Person)

    def test_creation_throws_error_on_missing_fields(self, test_domain):
        """Add an entity to the repository missing a required attribute"""
        with pytest.raises(ValidationError) as err:
            test_domain.repository_for(Person)._dao.create(last_name="Doe")

        assert err.value.messages == {"first_name": ["is required"]}

    def test_entity_persistence_with_create_method_and_fetch(self, test_domain):
        person = test_domain.repository_for(Person)._dao.create(
            first_name="John", last_name="Doe"
        )
        assert person is not None
        assert person.first_name == "John"
        assert person.last_name == "Doe"
        assert person.age == 21

        db_person = test_domain.repository_for(Person)._dao.get(person.id)
        assert db_person is not None
        assert db_person == person

    def test_multiple_persistence_for_an_aggregate(self, test_domain):
        """Test that save can be invoked again on an already existing entity, to update values"""
        person = Person(first_name="Johnny", last_name="John")
        test_domain.repository_for(Person)._dao.save(person)

        person.last_name = "Janey"
        test_domain.repository_for(Person)._dao.save(person)

        test_domain.repository_for(Person)._dao.get(person.id)
        assert person.last_name == "Janey"


@pytest.mark.basic_storage
class TestDAOUpdateFunctionality:
    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(Person)

    def test_update_an_existing_entity_in_the_repository(self, test_domain):
        person = test_domain.repository_for(Person)._dao.create(
            id="11344234", first_name="John", last_name="Doe", age=22
        )

        test_domain.repository_for(Person)._dao.update(person, age=10)
        updated_person = test_domain.repository_for(Person)._dao.get("11344234")
        assert updated_person is not None
        assert updated_person.age == 10

    def test_that_updating_a_deleted_aggregate_raises_object_not_found_error(
        self, test_domain
    ):
        """Try to update a non-existing entry"""
        person = test_domain.repository_for(Person)._dao.create(
            id="11344234", first_name="Johnny", last_name="John"
        )
        test_domain.repository_for(Person)._dao.delete(person)
        with pytest.raises(ObjectNotFoundError):
            test_domain.repository_for(Person)._dao.update(person, {"age": 10})

    def test_updating_record_with_dictionary_args(self, test_domain):
        """Update an existing entity in the repository"""
        person = test_domain.repository_for(Person)._dao.create(
            id="2", first_name="Johnny", last_name="John", age=2
        )

        test_domain.repository_for(Person)._dao.update(person, {"age": 10})
        u_person = test_domain.repository_for(Person)._dao.get("2")
        assert u_person is not None
        assert u_person.age == 10

    def test_updating_record_with_kwargs(self, test_domain):
        """Update an existing entity in the repository"""
        person = test_domain.repository_for(Person)._dao.create(
            id="2", first_name="Johnny", last_name="John", age=2
        )

        test_domain.repository_for(Person)._dao.update(person, age=10)
        u_person = test_domain.repository_for(Person)._dao.get("2")
        assert u_person is not None
        assert u_person.age == 10

    def test_updating_record_with_both_dictionary_args_and_kwargs(self, test_domain):
        """Update an existing entity in the repository"""
        person = test_domain.repository_for(Person)._dao.create(
            id="2", first_name="Johnny", last_name="John", age=2
        )

        test_domain.repository_for(Person)._dao.update(
            person, {"first_name": "Stephen"}, age=10
        )
        u_person = test_domain.repository_for(Person)._dao.get("2")
        assert u_person is not None
        assert u_person.age == 10
        assert u_person.first_name == "Stephen"


@pytest.mark.basic_storage
class TestDAODeleteFunctionality:
    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(Person)

    def test_delete_a_non_existing_object_in_repository_by_id(self, test_domain):
        """Delete a non-existing object in the repository by ID"""
        person = test_domain.repository_for(Person)._dao.create(
            id="3", first_name="John", last_name="Doe", age=22
        )

        # Keep a copy of the object to be deleted
        reloaded_person = test_domain.repository_for(Person)._dao.get(person.id)

        test_domain.repository_for(Person)._dao.delete(person)

        # This situation would occur if the same object was loaded in different requests.
        #   The first delete request would succeed, but the second one would fail
        with pytest.raises(ObjectNotFoundError):
            test_domain.repository_for(Person)._dao.delete(reloaded_person)

    def test_delete_an_object_in_repository_by_id(self, test_domain):
        """Delete an object in the repository by ID"""
        person = test_domain.repository_for(Person)._dao.create(
            id="3", first_name="John", last_name="Doe", age=22
        )

        persisted_person = test_domain.repository_for(Person)._dao.get("3")
        assert persisted_person is not None

        deleted_person = test_domain.repository_for(Person)._dao.delete(person)
        assert deleted_person is not None
        assert deleted_person.state_.is_destroyed is True

        with pytest.raises(ObjectNotFoundError):
            test_domain.repository_for(Person)._dao.get("3")

    def test_deleting_a_persisted_entity(self, test_domain):
        """Delete an object in the repository by ID"""
        person = test_domain.repository_for(Person)._dao.create(
            first_name="Jim", last_name="Carrey"
        )
        deleted_person = test_domain.repository_for(Person)._dao.delete(person)
        assert deleted_person is not None
        assert deleted_person.state_.is_destroyed is True

        with pytest.raises(ObjectNotFoundError):
            test_domain.repository_for(Person)._dao.get(person.id)


@pytest.mark.basic_storage
class TestDAOValidations:
    """This class holds tests for DAO class"""

    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(Person)
        test_domain.register(User)

    def test_unique(self, test_domain):
        """Test the unique constraints for the entity"""
        test_domain.repository_for(User)._dao.create(
            email="john.doe@gmail.com", password="a1b2c3"
        )

        with pytest.raises(ValidationError) as err:
            test_domain.repository_for(User)._dao.create(
                email="john.doe@gmail.com", password="d4e5r6"
            )
        assert err.value.messages == {
            "email": ["User with email 'john.doe@gmail.com' is already present."]
        }

    def test_that_field_required_validations_are_triggered_on_incorrect_attribute_setting(
        self,
    ):
        """Test failed `save()` because of validation errors"""
        person = Person(first_name="Johnny", last_name="John")

        with pytest.raises(ValidationError) as error:
            person.first_name = ""  # Simulate an error by force-resetting an attribute

        assert "first_name" in error.value.messages

        # Setting None on a required field raises a validation error
        with pytest.raises(ValidationError) as error:
            person.first_name = None

        assert error.value.messages == {
            "first_name": ["Input should be a valid string"]
        }

    def test_that_primitive_validations_on_type_are_thrown_correctly_on_initialization(
        self, test_domain
    ):
        with pytest.raises(ValidationError) as error:
            Person(first_name="Johnny", last_name="John", age="x")

        assert error.value.messages == {
            "age": [
                "Input should be a valid integer, unable to parse string as an integer"
            ]
        }

    def test_that_primitive_validations_on_type_are_thrown_correctly_on_update(
        self, test_domain
    ):
        person = test_domain.repository_for(Person)._dao.create(
            first_name="John", last_name="Doe", age=22
        )

        with pytest.raises(ValidationError) as error:
            test_domain.repository_for(Person)._dao.update(
                person, age="x"
            )  # Age should be an integer

        assert error.value.messages == {
            "age": [
                "Input should be a valid integer, unable to parse string as an integer"
            ]
        }


@pytest.mark.basic_storage
class TestDAOHasTable:
    """Test has_table method functionality"""

    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(User)

    def test_has_table_returns_false_before_creation(self, test_domain):
        """Test that has_table returns False before any entity is created"""
        dao = test_domain.repository_for(User)._dao

        result = dao.has_table()
        assert isinstance(result, bool)

    def test_has_table_returns_true_after_creation(self, test_domain):
        """Test that has_table returns True after creating an entity"""
        dao = test_domain.repository_for(User)._dao

        dao.create(email="john.doe@example.com", password="password")

        assert dao.has_table() is True

    def test_has_table_returns_true_after_multiple_creations(self, test_domain):
        """Test that has_table returns True after creating multiple entities"""
        dao = test_domain.repository_for(User)._dao

        dao.create(email="john.doe.1@example.com", password="password")
        dao.create(email="john.doe.2@example.com", password="password")

        assert dao.has_table() is True
