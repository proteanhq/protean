"""Tests for aggregate persistence through the memory repository.

Validates:
- Basic CRUD operations (add, retrieve, update, delete, filter)
- State tracking through the persistence lifecycle
- Version tracking and optimistic concurrency
"""

from uuid import uuid4

import pytest
from pydantic import Field

from protean.core.aggregate import BaseAggregate
from protean.core.repository import BaseRepository
from protean.exceptions import ExpectedVersionError, ObjectNotFoundError


# ---------------------------------------------------------------------------
# Test domain elements
# ---------------------------------------------------------------------------
class Person(BaseAggregate):
    id: str = Field(
        json_schema_extra={"identifier": True},
        default_factory=lambda: str(uuid4()),
    )
    first_name: str
    last_name: str
    age: int = 21


class PersonRepository(BaseRepository):
    pass


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Person)
    test_domain.register(PersonRepository, part_of=Person)
    test_domain.init(traverse=False)


# ---------------------------------------------------------------------------
# Tests: Basic CRUD
# ---------------------------------------------------------------------------
@pytest.mark.database
@pytest.mark.usefixtures("db")
class TestAggregateCRUD:
    def test_add_and_retrieve(self, test_domain):
        repo = test_domain.repository_for(Person)
        person = Person(first_name="John", last_name="Doe", age=30)
        repo.add(person)

        persisted = repo.get(person.id)
        assert persisted.first_name == "John"
        assert persisted.last_name == "Doe"
        assert persisted.age == 30
        assert persisted.id == person.id

    def test_add_with_explicit_id(self, test_domain):
        repo = test_domain.repository_for(Person)
        uid = str(uuid4())
        person = Person(id=uid, first_name="Jane", last_name="Doe")
        repo.add(person)

        persisted = repo.get(uid)
        assert persisted.id == uid
        assert persisted.first_name == "Jane"

    def test_update_via_repository(self, test_domain):
        repo = test_domain.repository_for(Person)
        person = Person(first_name="John", last_name="Doe")
        repo.add(person)

        persisted = repo.get(person.id)
        persisted.last_name = "Dane"
        repo.add(persisted)

        updated = repo.get(person.id)
        assert updated.last_name == "Dane"

    def test_delete_via_dao(self, test_domain):
        repo = test_domain.repository_for(Person)
        person = Person(first_name="John", last_name="Doe")
        repo.add(person)

        assert repo.get(person.id) is not None

        repo._dao.delete(person)

        with pytest.raises(ObjectNotFoundError):
            repo.get(person.id)

    def test_filter_by_criteria(self, test_domain):
        repo = test_domain.repository_for(Person)
        repo.add(Person(first_name="John", last_name="Doe", age=30))
        repo.add(Person(first_name="Jane", last_name="Doe", age=25))
        repo.add(Person(first_name="Bob", last_name="Smith", age=40))

        results = repo._dao.query.filter(last_name="Doe").all()
        assert len(results) == 2

    def test_count(self, test_domain):
        repo = test_domain.repository_for(Person)
        repo.add(Person(first_name="John", last_name="Doe"))
        repo.add(Person(first_name="Jane", last_name="Doe"))

        results = repo._dao.query.all()
        assert results.total == 2

    def test_default_values_persisted(self, test_domain):
        repo = test_domain.repository_for(Person)
        person = Person(first_name="John", last_name="Doe")
        repo.add(person)

        persisted = repo.get(person.id)
        assert persisted.age == 21


# ---------------------------------------------------------------------------
# Tests: State Tracking
# ---------------------------------------------------------------------------
@pytest.mark.database
@pytest.mark.usefixtures("db")
class TestAggregateStateTracking:
    def test_new_state_before_persist(self):
        person = Person(first_name="John", last_name="Doe")
        assert person.state_.is_new is True
        assert person.state_.is_persisted is False

    def test_persisted_state_after_add(self, test_domain):
        repo = test_domain.repository_for(Person)
        person = Person(first_name="John", last_name="Doe")
        repo.add(person)

        assert person.state_.is_new is False
        assert person.state_.is_persisted is True

    def test_retrieved_state(self, test_domain):
        repo = test_domain.repository_for(Person)
        person = Person(first_name="John", last_name="Doe")
        repo.add(person)

        persisted = repo.get(person.id)
        assert persisted.state_.is_new is False
        assert persisted.state_.is_persisted is True

    def test_changed_state_after_mutation(self, test_domain):
        repo = test_domain.repository_for(Person)
        person = Person(first_name="John", last_name="Doe")
        repo.add(person)

        persisted = repo.get(person.id)
        persisted.first_name = "Jane"
        assert persisted.state_.is_changed is True

    def test_state_reset_after_re_add(self, test_domain):
        repo = test_domain.repository_for(Person)
        person = Person(first_name="John", last_name="Doe")
        repo.add(person)

        persisted = repo.get(person.id)
        persisted.first_name = "Jane"
        repo.add(persisted)

        assert persisted.state_.is_changed is False
        assert persisted.state_.is_persisted is True


# ---------------------------------------------------------------------------
# Tests: Version Tracking
# ---------------------------------------------------------------------------
@pytest.mark.database
@pytest.mark.usefixtures("db")
class TestAggregateVersionTracking:
    def test_initial_version(self):
        person = Person(first_name="John", last_name="Doe")
        assert person._version == -1

    def test_version_after_first_save(self, test_domain):
        repo = test_domain.repository_for(Person)
        person = Person(first_name="John", last_name="Doe")
        repo.add(person)

        assert person._version == 0

    def test_version_survives_round_trip(self, test_domain):
        """Critical: version must persist and be restored on retrieval."""
        repo = test_domain.repository_for(Person)
        person = Person(first_name="John", last_name="Doe")
        repo.add(person)

        persisted = repo.get(person.id)
        assert persisted._version == 0

    def test_version_after_second_save(self, test_domain):
        """Validates optimistic concurrency works across saves."""
        repo = test_domain.repository_for(Person)
        person = Person(first_name="John", last_name="Doe")
        repo.add(person)

        persisted = repo.get(person.id)
        persisted.first_name = "Jane"
        repo.add(persisted)

        assert persisted._version == 1

    def test_version_conflict_detected(self, test_domain):
        """Two concurrent readers should detect version conflict."""
        repo = test_domain.repository_for(Person)
        person = Person(first_name="John", last_name="Doe")
        repo.add(person)

        reader1 = repo.get(person.id)
        reader2 = repo.get(person.id)

        reader1.first_name = "Jane"
        repo.add(reader1)

        reader2.first_name = "Bob"
        with pytest.raises(ExpectedVersionError):
            repo.add(reader2)
