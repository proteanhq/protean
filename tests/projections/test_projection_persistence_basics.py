"""Tests for projection persistence through the memory repository.

Validates:
- Basic CRUD operations (add, retrieve, update, delete, filter)
- State tracking through the persistence lifecycle
- Optional/None field persistence
"""

import pytest
from pydantic import Field

from protean.core.projection import BaseProjection
from protean.exceptions import ObjectNotFoundError


# ---------------------------------------------------------------------------
# Test domain elements
# ---------------------------------------------------------------------------
class PersonProjection(BaseProjection):
    person_id: str = Field(json_schema_extra={"identifier": True})
    first_name: str
    last_name: str | None = None
    age: int = 21


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(PersonProjection)
    test_domain.init(traverse=False)


# ---------------------------------------------------------------------------
# Tests: Basic CRUD
# ---------------------------------------------------------------------------
@pytest.mark.database
@pytest.mark.usefixtures("db")
class TestProjectionCRUD:
    def test_persist_and_retrieve(self, test_domain):
        repo = test_domain.repository_for(PersonProjection)
        person = PersonProjection(
            person_id="1", first_name="John", last_name="Doe", age=25
        )
        repo.add(person)

        refreshed = repo.get("1")
        assert refreshed.person_id == "1"
        assert refreshed.first_name == "John"
        assert refreshed.last_name == "Doe"
        assert refreshed.age == 25

    def test_update(self, test_domain):
        repo = test_domain.repository_for(PersonProjection)
        person = PersonProjection(
            person_id="1", first_name="John", last_name="Doe", age=25
        )
        repo.add(person)

        person.first_name = "Jane"
        repo.add(person)

        refreshed = repo.get("1")
        assert refreshed.first_name == "Jane"
        assert refreshed.last_name == "Doe"

    def test_delete(self, test_domain):
        repo = test_domain.repository_for(PersonProjection)
        person = PersonProjection(person_id="1", first_name="John")
        repo.add(person)

        repo._dao.delete(person)

        with pytest.raises(ObjectNotFoundError):
            repo.get("1")

    def test_filter(self, test_domain):
        repo = test_domain.repository_for(PersonProjection)
        repo.add(PersonProjection(person_id="1", first_name="John", last_name="Doe"))
        repo.add(PersonProjection(person_id="2", first_name="Jane", last_name="Doe"))
        repo.add(PersonProjection(person_id="3", first_name="Bob", last_name="Smith"))

        results = repo._dao.query.filter(last_name="Doe").all()
        assert len(results) == 2

    def test_default_values_persisted(self, test_domain):
        repo = test_domain.repository_for(PersonProjection)
        person = PersonProjection(person_id="1", first_name="John")
        repo.add(person)

        refreshed = repo.get("1")
        assert refreshed.age == 21

    def test_optional_none_fields_persisted(self, test_domain):
        repo = test_domain.repository_for(PersonProjection)
        person = PersonProjection(person_id="1", first_name="John")
        repo.add(person)

        refreshed = repo.get("1")
        assert refreshed.last_name is None


# ---------------------------------------------------------------------------
# Tests: State Tracking
# ---------------------------------------------------------------------------
@pytest.mark.database
@pytest.mark.usefixtures("db")
class TestProjectionStateTracking:
    def test_new_state_before_persist(self):
        person = PersonProjection(person_id="1", first_name="John")
        assert person.state_.is_new is True

    def test_persisted_state_after_add(self, test_domain):
        repo = test_domain.repository_for(PersonProjection)
        person = PersonProjection(person_id="1", first_name="John")
        repo.add(person)

        assert person.state_.is_persisted is True

    def test_retrieved_state(self, test_domain):
        repo = test_domain.repository_for(PersonProjection)
        person = PersonProjection(person_id="1", first_name="John")
        repo.add(person)

        refreshed = repo.get("1")
        assert refreshed.state_.is_persisted is True
        assert refreshed.state_.is_new is False
