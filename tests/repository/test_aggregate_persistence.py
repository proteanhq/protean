import pytest

from protean.exceptions import ObjectNotFoundError

from .elements import Person, PersonRepository


class TestAggregatePersistenceWithMemoryProvider:
    def test_retrieval_from_provider_connection(self, test_domain):
        conn = test_domain.get_connection()
        assert conn is not None

        conn._db["data"]["foo"] = "bar"

        assert "foo" in conn._db["data"]
        assert conn._db["data"]["foo"] == "bar"


class TestAggregatePersistenceWithRepository:
    @pytest.fixture(autouse=True)
    def register_repositories(self, test_domain):
        test_domain.register(Person)
        test_domain.register(PersonRepository)
        yield

    @pytest.fixture
    def person_dao(self, test_domain):
        return test_domain.get_dao(Person)

    def test_new_object_persistence_with_no_uow(self, test_domain):
        repo = test_domain.repository_for(Person)
        person = Person(first_name="John", last_name="Doe")
        repo.add(person)

        persisted_person = repo.get(person.id)
        assert persisted_person is not None

    def test_object_update_with_no_uow(self, test_domain):
        # Add a Person to the repository
        repo = test_domain.repository_for(Person)
        person = Person(first_name="John", last_name="Doe")
        repo.add(person)

        # Fetch person record back
        persisted_person = repo.get(person.id)
        assert persisted_person.last_name == "Doe"

        # Edit and update the person record
        persisted_person.last_name = "Dane"
        repo.add(persisted_person)

        # Re-fetch and check that the details have changed
        updated_person = repo.get(person.id)
        assert updated_person.last_name == "Dane"

    def test_object_delete_with_no_uow(self, test_domain):
        # Add a Person to the repository
        repo = test_domain.repository_for(Person)
        person = Person(first_name="John", last_name="Doe")
        repo.add(person)

        # Remove the person from repository
        repo.remove(person)

        # Re-fetch and check that the details have changed
        with pytest.raises(ObjectNotFoundError):
            repo.get(person.id)

    def test_that_an_aggregate_object_can_be_persisted_via_dao(self, person_dao):
        person = Person(first_name="John", last_name="Doe", age=35)
        persisted_person = person_dao.save(person)

        assert persisted_person is not None
