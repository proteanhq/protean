"""Tests for the repository `query` property, `find_by`, `find`, and `exists` methods.

Validates that custom repository methods can use `self.query`,
`self.find_by`, `self.find`, and `self.exists` instead of reaching
through `self._dao`.
"""

from uuid import uuid4

import pytest
from pydantic import Field

from protean.core.aggregate import BaseAggregate
from protean.core.queryset import QuerySet, ResultSet
from protean.core.repository import BaseRepository
from protean.exceptions import ObjectNotFoundError, TooManyObjectsError
from protean.utils.query import Q


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
    country: str = ""


class PersonRepository(BaseRepository):
    def adults(self) -> list:
        return self.query.filter(age__gte=18).all().items

    def find_by_name(self, first_name: str) -> Person:
        return self.find_by(first_name=first_name)

    def by_country(self, country_code: str) -> list:
        return self.query.filter(country=country_code).all().items


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Person)
    test_domain.register(PersonRepository, part_of=Person)
    test_domain.init(traverse=False)


@pytest.fixture()
def seed_people(test_domain):
    repo = test_domain.repository_for(Person)
    repo.add(Person(first_name="Alice", last_name="A", age=30, country="US"))
    repo.add(Person(first_name="Bob", last_name="B", age=16, country="CA"))
    repo.add(Person(first_name="Charlie", last_name="C", age=25, country="US"))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
@pytest.mark.database
@pytest.mark.usefixtures("db")
class TestQueryProperty:
    def test_query_returns_queryset(self, test_domain):
        repo = test_domain.repository_for(Person)
        assert isinstance(repo.query, QuerySet)

    def test_query_filter(self, test_domain, seed_people):
        repo = test_domain.repository_for(Person)
        results = repo.query.filter(country="US").all()
        assert results.total == 2
        names = {p.first_name for p in results.items}
        assert names == {"Alice", "Charlie"}

    def test_query_filter_via_custom_method(self, test_domain, seed_people):
        repo = test_domain.repository_for(Person)
        adults = repo.adults()
        assert len(adults) == 2
        names = {p.first_name for p in adults}
        assert names == {"Alice", "Charlie"}

    def test_query_by_country_via_custom_method(self, test_domain, seed_people):
        repo = test_domain.repository_for(Person)
        canadians = repo.by_country("CA")
        assert len(canadians) == 1
        assert canadians[0].first_name == "Bob"

    def test_query_with_chained_filters(self, test_domain, seed_people):
        repo = test_domain.repository_for(Person)
        results = repo.query.filter(country="US").filter(age__gte=28).all()
        assert results.total == 1
        assert results.first.first_name == "Alice"


@pytest.mark.database
@pytest.mark.usefixtures("db")
class TestFindBy:
    def test_find_by_returns_single_aggregate(self, test_domain, seed_people):
        repo = test_domain.repository_for(Person)
        person = repo.find_by(first_name="Alice")
        assert person.first_name == "Alice"
        assert person.age == 30

    def test_find_by_via_custom_method(self, test_domain, seed_people):
        repo = test_domain.repository_for(Person)
        person = repo.find_by_name("Bob")
        assert person.first_name == "Bob"

    def test_find_by_raises_not_found(self, test_domain, seed_people):
        repo = test_domain.repository_for(Person)
        with pytest.raises(ObjectNotFoundError):
            repo.find_by(first_name="Nobody")

    def test_find_by_raises_too_many(self, test_domain, seed_people):
        repo = test_domain.repository_for(Person)
        with pytest.raises(TooManyObjectsError):
            repo.find_by(country="US")


@pytest.mark.database
@pytest.mark.usefixtures("db")
class TestFind:
    def test_find_returns_resultset(self, test_domain, seed_people):
        repo = test_domain.repository_for(Person)
        results = repo.find(Q(country="US"))
        assert isinstance(results, ResultSet)

    def test_find_with_simple_criteria(self, test_domain, seed_people):
        repo = test_domain.repository_for(Person)
        results = repo.find(Q(country="US"))
        assert results.total == 2
        names = {p.first_name for p in results.items}
        assert names == {"Alice", "Charlie"}

    def test_find_with_lookup_operator(self, test_domain, seed_people):
        repo = test_domain.repository_for(Person)
        results = repo.find(Q(age__gte=18))
        assert results.total == 2
        names = {p.first_name for p in results.items}
        assert names == {"Alice", "Charlie"}

    def test_find_with_and_composition(self, test_domain, seed_people):
        repo = test_domain.repository_for(Person)
        results = repo.find(Q(country="US") & Q(age__gte=28))
        assert results.total == 1
        assert results.first.first_name == "Alice"

    def test_find_with_or_composition(self, test_domain, seed_people):
        repo = test_domain.repository_for(Person)
        results = repo.find(Q(first_name="Alice") | Q(first_name="Bob"))
        assert results.total == 2
        names = {p.first_name for p in results.items}
        assert names == {"Alice", "Bob"}

    def test_find_with_negation(self, test_domain, seed_people):
        repo = test_domain.repository_for(Person)
        results = repo.find(~Q(country="US"))
        assert results.total == 1
        assert results.first.first_name == "Bob"

    def test_find_with_no_matches(self, test_domain, seed_people):
        repo = test_domain.repository_for(Person)
        results = repo.find(Q(country="UK"))
        assert results.total == 0
        assert results.items == []

    def test_find_with_reusable_q_function(self, test_domain, seed_people):
        """Verify the Q-function composition pattern works with find()."""

        def adults() -> Q:
            return Q(age__gte=18)

        def in_country(country: str) -> Q:
            return Q(country=country)

        repo = test_domain.repository_for(Person)
        results = repo.find(adults() & in_country("US"))
        assert results.total == 2
        names = {p.first_name for p in results.items}
        assert names == {"Alice", "Charlie"}

    def test_find_in_custom_repository_method(self, test_domain, seed_people):
        """Verify find() is accessible from custom repository methods."""
        repo = test_domain.repository_for(Person)
        # Use find() directly on the repo (not through a custom method,
        # but validates the method is available on the instance)
        results = repo.find(Q(age__gte=18, country="US"))
        assert results.total == 2


@pytest.mark.database
@pytest.mark.usefixtures("db")
class TestExists:
    def test_exists_returns_true_when_matching(self, test_domain, seed_people):
        repo = test_domain.repository_for(Person)
        assert repo.exists(Q(country="US")) is True

    def test_exists_returns_false_when_no_match(self, test_domain, seed_people):
        repo = test_domain.repository_for(Person)
        assert repo.exists(Q(country="UK")) is False

    def test_exists_with_composed_criteria(self, test_domain, seed_people):
        repo = test_domain.repository_for(Person)
        assert repo.exists(Q(country="US") & Q(age__gte=28)) is True
        assert repo.exists(Q(country="CA") & Q(age__gte=28)) is False

    def test_exists_with_negation(self, test_domain, seed_people):
        repo = test_domain.repository_for(Person)
        assert repo.exists(~Q(country="US")) is True  # Bob is in CA

    def test_exists_on_empty_store(self, test_domain):
        repo = test_domain.repository_for(Person)
        assert repo.exists(Q(country="US")) is False
