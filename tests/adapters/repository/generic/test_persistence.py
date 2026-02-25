"""Generic persistence tests that run against all database providers.

Covers repository-level persistence, retrieval, and concurrency control.
Merged from test_generic.py and test_persistence.py.
"""

import re
from datetime import datetime
from typing import List
from uuid import uuid4

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.entity import invariant
from protean.core.repository import BaseRepository
from protean.core.unit_of_work import UnitOfWork
from protean.core.value_object import BaseValueObject
from protean.exceptions import ExpectedVersionError, ValidationError
from protean.fields import DateTime, Integer, String, ValueObject


class Person(BaseAggregate):
    first_name: String(max_length=50, required=True)
    last_name: String(max_length=50, required=True)
    age: Integer(default=21)


class PersonRepository(BaseRepository):
    def find_adults(self, minimum_age: int = 21) -> List[Person]:
        return self.query.filter(age__gte=minimum_age).all().items


class Email(BaseValueObject):
    REGEXP = r"\"?([-a-zA-Z0-9.`?{}]+@\w+\.\w+)\"?"

    # This is the external facing data attribute
    address: String(max_length=254, required=True)

    @invariant.post
    def validate_email_address(self):
        """Business rules of Email address"""
        if not bool(re.match(Email.REGEXP, self.address)):
            raise ValidationError({"address": ["email address"]})


class User(BaseAggregate):
    email = ValueObject(Email, required=True)
    password: String(required=True, max_length=255)


class Event(BaseAggregate):
    name: String(max_length=255, required=True)
    created_at: DateTime(default=datetime.now)
    sequence_id: Integer()


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Person)
    test_domain.register(PersonRepository, part_of=Person)
    test_domain.register(User)
    test_domain.register(Event)


@pytest.mark.basic_storage
class TestPersistenceViaRepository:
    def test_that_aggregate_can_be_persisted_with_repository(self, test_domain):
        test_domain.repository_for(Person).add(
            Person(first_name="John", last_name="Doe")
        )

        assert len(test_domain.repository_for(Person).query.all().items) == 1

    def test_that_an_aggregate_can_be_retrieved_with_repository(self, test_domain):
        person = Person(first_name="John", last_name="Doe")
        test_domain.repository_for(Person).add(person)

        assert test_domain.repository_for(Person).get(person.id) == person

    def test_that_all_aggregates_can_be_retrieved_with_repository(self, test_domain):
        person = Person(first_name="John", last_name="Doe")
        test_domain.repository_for(Person).add(person)

        assert test_domain.repository_for(Person).query.all().items == [person]


@pytest.mark.basic_storage
class TestBasicPersistence:
    """Test basic persistence operations across databases"""

    def test_persist_and_retrieve_entity(self, test_domain):
        """Test basic entity persistence and retrieval"""
        event = Event(name="TestEvent", sequence_id=1)
        test_domain.repository_for(Event).add(event)

        retrieved_event = test_domain.repository_for(Event).get(event.id)

        assert retrieved_event.id == event.id
        assert retrieved_event.name == event.name
        assert retrieved_event.sequence_id == event.sequence_id

    def test_entity_update(self, test_domain):
        """Test entity update operations"""
        event = Event(name="TestEvent", sequence_id=1)
        test_domain.repository_for(Event).add(event)

        # Fetch the event again
        retrieved_event = test_domain.repository_for(Event).get(event.id)

        # Update the event
        retrieved_event.name = "UpdatedEvent"
        retrieved_event.sequence_id = 2
        test_domain.repository_for(Event).add(retrieved_event)

        # Retrieve and verify
        retrieved_event = test_domain.repository_for(Event).get(event.id)
        assert retrieved_event.name == "UpdatedEvent"
        assert retrieved_event.sequence_id == 2


@pytest.mark.basic_storage
class TestConcurrency:
    def test_expected_version_error_on_version_mismatch(self, test_domain):
        identifier = str(uuid4())

        with UnitOfWork():
            repo = test_domain.repository_for(Person)
            person = Person(id=identifier, first_name="John", last_name="Doe")
            repo.add(person)

        person_dup1 = repo.get(identifier)
        person_dup2 = repo.get(identifier)

        with UnitOfWork():
            person_dup1.first_name = "Jane"
            repo.add(person_dup1)

        with pytest.raises(ExpectedVersionError) as exc:
            with UnitOfWork():
                person_dup2.first_name = "Baby"
                repo.add(person_dup2)

        assert exc.value.args[0] == (
            f"Wrong expected version: {person_dup2._version} "
            f"(Aggregate: Person({identifier}), Version: {person_dup2._version + 1})"
        )
