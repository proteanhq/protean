import re

from collections import defaultdict
from typing import List
from uuid import uuid4

import pytest

from protean import BaseAggregate, BaseRepository, BaseValueObject, UnitOfWork
from protean.exceptions import ExpectedVersionError
from protean.fields import Integer, String, ValueObject
from protean.globals import current_domain


class Person(BaseAggregate):
    first_name = String(max_length=50, required=True)
    last_name = String(max_length=50, required=True)
    age = Integer(default=21)


class PersonRepository(BaseRepository):
    def find_adults(self, minimum_age: int = 21) -> List[Person]:
        return current_domain.repository_for(Person)._dao.filter(age__gte=minimum_age)

    class Meta:
        aggregate_cls = Person


class Email(BaseValueObject):
    REGEXP = r"\"?([-a-zA-Z0-9.`?{}]+@\w+\.\w+)\"?"

    # This is the external facing data attribute
    address = String(max_length=254, required=True)

    def clean(self):
        """Business rules of Email address"""
        errors = defaultdict(list)

        if not bool(re.match(Email.REGEXP, self.address)):
            errors["address"].append("is invalid")

        return errors


class User(BaseAggregate):
    email = ValueObject(Email, required=True)
    password = String(required=True, max_length=255)


def initialize_domain():
    from protean.domain import Domain

    domain = Domain("Database Tests")
    return domain


@pytest.fixture
def test_domain(db_config):
    domain = initialize_domain()
    domain.config["DATABASES"] = {
        "default": db_config,
        "memory": {"PROVIDER": "protean.adapters.MemoryProvider"},
    }

    with domain.domain_context():
        yield domain


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Person)
    test_domain.register(PersonRepository)
    test_domain.register(User)


@pytest.fixture(scope="session", autouse=True)
def setup_db(db_config):
    domain = initialize_domain()
    domain.config["DATABASES"] = {"default": db_config}

    with domain.domain_context():
        elements = [Person, User]

        for element in elements:
            domain.register(element)

        # Call provider to create structures
        domain.providers["default"]._create_database_artifacts()

        yield

        # Drop structures
        domain.providers["default"]._drop_database_artifacts()


class TestPersistenceViaRepository:
    def test_that_aggregate_can_be_persisted_with_repository(self, test_domain):
        test_domain.repository_for(Person).add(
            Person(first_name="John", last_name="Doe")
        )

        assert len(test_domain.repository_for(Person)._dao.query.all().items) == 1

    def test_that_an_aggregate_can_be_retrieved_with_repository(self, test_domain):
        person = Person(first_name="John", last_name="Doe")
        test_domain.repository_for(Person).add(person)

        assert test_domain.repository_for(Person).get(person.id) == person

    def test_that_all_aggregates_can_be_retrieved_with_repository(self, test_domain):
        person = Person(first_name="John", last_name="Doe")
        test_domain.repository_for(Person).add(person)

        assert test_domain.repository_for(Person).all() == [person]


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
            f"(Aggregate: Person({identifier}), Version: {person_dup2._version+1})"
        )
