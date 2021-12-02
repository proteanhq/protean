from uuid import uuid4

import pytest

from .elements import Person


@pytest.mark.elasticsearch
class TestElasticsearchRepository:
    """This class holds tests for DAO class"""

    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(Person)

    @pytest.fixture
    def identifier(self):
        return uuid4()

    @pytest.fixture
    def persisted_person(self, test_domain, identifier):
        person = test_domain.repository_for(Person)._dao.create(
            id=identifier, first_name="John", last_name="Doe"
        )
        return person

    def test_retrieval_by_identifier(self, test_domain, identifier, persisted_person):
        person_repo = test_domain.repository_for(Person)
        person = person_repo.get(identifier)

        assert person is not None
        assert person == persisted_person
        assert person.id == identifier

    def test_persistence_through_repository(self, test_domain):
        person_repo = test_domain.repository_for(Person)
        person = Person(first_name="John", last_name="Doe")
        person_repo.add(person)

        persisted_person = test_domain.repository_for(Person)._dao.get(person.id)
        assert persisted_person is not None
        assert persisted_person == person
