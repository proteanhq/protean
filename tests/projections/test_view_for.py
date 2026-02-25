"""Tests for domain.view_for() and ReadView.

Validates:
- domain.view_for() returns a ReadView for projections
- domain.view_for() rejects non-projection types
- ReadView.get() retrieves by identifier (database and cache)
- ReadView.query returns ReadOnlyQuerySet (database only)
- ReadView.find_by() finds by criteria (database only)
- ReadView.count() returns total record count
- ReadView.exists() checks existence by identifier
- ReadView does not expose write methods (add, _dao, delete)
- Cache-backed projections: query and find_by raise NotSupportedError
- ReadView and repository_for see the same data
"""

import pytest
from pydantic import Field

from protean.core.aggregate import BaseAggregate
from protean.core.projection import BaseProjection
from protean.core.queryset import ReadOnlyQuerySet
from protean.core.view import ReadView
from protean.exceptions import (
    IncorrectUsageError,
    NotSupportedError,
    ObjectNotFoundError,
    TooManyObjectsError,
)


# ---------------------------------------------------------------------------
# Test domain elements
# ---------------------------------------------------------------------------
class PersonProjection(BaseProjection):
    person_id: str = Field(json_schema_extra={"identifier": True})
    first_name: str
    last_name: str | None = None
    age: int = 21


class Person(BaseAggregate):
    first_name: str
    last_name: str | None = None
    age: int = 21


class CachedPersonProjection(BaseProjection):
    person_id: str = Field(json_schema_extra={"identifier": True})
    first_name: str
    last_name: str | None = None


# ---------------------------------------------------------------------------
# Fixtures: database-backed
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(PersonProjection)
    test_domain.register(Person)
    test_domain.init(traverse=False)


@pytest.fixture
def seeded_projections(test_domain):
    repo = test_domain.repository_for(PersonProjection)
    repo.add(
        PersonProjection(person_id="1", first_name="John", last_name="Doe", age=38)
    )
    repo.add(
        PersonProjection(person_id="2", first_name="Jane", last_name="Doe", age=36)
    )
    repo.add(
        PersonProjection(person_id="3", first_name="Bob", last_name="Smith", age=25)
    )
    repo.add(PersonProjection(person_id="4", first_name="Baby", last_name="Doe", age=3))


# ---------------------------------------------------------------------------
# Tests: domain.view_for() — entry point
# ---------------------------------------------------------------------------
@pytest.mark.database
@pytest.mark.usefixtures("db")
class TestViewForEntryPoint:
    def test_returns_read_view_instance(self, test_domain):
        view = test_domain.view_for(PersonProjection)
        assert isinstance(view, ReadView)

    def test_rejects_aggregate_class(self, test_domain):
        with pytest.raises(IncorrectUsageError, match="only available for projections"):
            test_domain.view_for(Person)

    def test_rejects_string_argument(self, test_domain):
        with pytest.raises(IncorrectUsageError, match="not registered"):
            test_domain.view_for("PersonProjection")


# ---------------------------------------------------------------------------
# Tests: ReadView.get()
# ---------------------------------------------------------------------------
@pytest.mark.database
@pytest.mark.usefixtures("db")
class TestReadViewGet:
    def test_get_by_identifier(self, test_domain, seeded_projections):
        view = test_domain.view_for(PersonProjection)
        person = view.get("1")

        assert person.first_name == "John"
        assert person.last_name == "Doe"
        assert person.age == 38

    def test_get_nonexistent_raises_not_found(self, test_domain):
        view = test_domain.view_for(PersonProjection)

        with pytest.raises(ObjectNotFoundError):
            view.get("nonexistent")


# ---------------------------------------------------------------------------
# Tests: ReadView.query
# ---------------------------------------------------------------------------
@pytest.mark.database
@pytest.mark.usefixtures("db")
class TestReadViewQuery:
    def test_query_returns_read_only_queryset(self, test_domain):
        view = test_domain.view_for(PersonProjection)
        assert isinstance(view.query, ReadOnlyQuerySet)

    def test_query_filter_and_all(self, test_domain, seeded_projections):
        view = test_domain.view_for(PersonProjection)
        results = view.query.filter(last_name="Doe").all()

        assert results.total == 3
        names = {item.first_name for item in results}
        assert names == {"John", "Jane", "Baby"}

    def test_query_exclude(self, test_domain, seeded_projections):
        view = test_domain.view_for(PersonProjection)
        results = view.query.exclude(last_name="Doe").all()

        assert results.total == 1
        assert results.first.first_name == "Bob"

    def test_query_order_by(self, test_domain, seeded_projections):
        view = test_domain.view_for(PersonProjection)
        results = view.query.order_by("age").all()

        ages = [item.age for item in results]
        assert ages == [3, 25, 36, 38]

    def test_query_limit_and_offset(self, test_domain, seeded_projections):
        view = test_domain.view_for(PersonProjection)
        results = view.query.order_by("age").limit(2).offset(1).all()

        assert len(results.items) == 2
        ages = [item.age for item in results]
        assert ages == [25, 36]

    def test_query_mutation_blocked(self, test_domain):
        view = test_domain.view_for(PersonProjection)

        with pytest.raises(NotSupportedError):
            view.query.update(first_name="X")

        with pytest.raises(NotSupportedError):
            view.query.delete()

    def test_successive_query_calls_return_fresh_queryset(self, test_domain):
        view = test_domain.view_for(PersonProjection)
        qs1 = view.query
        qs2 = view.query

        assert qs1 is not qs2
        assert isinstance(qs1, ReadOnlyQuerySet)
        assert isinstance(qs2, ReadOnlyQuerySet)


# ---------------------------------------------------------------------------
# Tests: ReadView.find_by()
# ---------------------------------------------------------------------------
@pytest.mark.database
@pytest.mark.usefixtures("db")
class TestReadViewFindBy:
    def test_find_by_single_field(self, test_domain, seeded_projections):
        view = test_domain.view_for(PersonProjection)
        person = view.find_by(first_name="Bob")

        assert person.last_name == "Smith"
        assert person.age == 25

    def test_find_by_nonexistent_raises_not_found(self, test_domain):
        view = test_domain.view_for(PersonProjection)

        with pytest.raises(ObjectNotFoundError):
            view.find_by(first_name="Nonexistent")

    def test_find_by_multiple_results_raises_too_many(
        self, test_domain, seeded_projections
    ):
        view = test_domain.view_for(PersonProjection)

        with pytest.raises(TooManyObjectsError):
            view.find_by(last_name="Doe")


# ---------------------------------------------------------------------------
# Tests: ReadView.count()
# ---------------------------------------------------------------------------
@pytest.mark.database
@pytest.mark.usefixtures("db")
class TestReadViewCount:
    def test_count_all(self, test_domain, seeded_projections):
        view = test_domain.view_for(PersonProjection)
        assert view.count() == 4

    def test_count_empty(self, test_domain):
        view = test_domain.view_for(PersonProjection)
        assert view.count() == 0


# ---------------------------------------------------------------------------
# Tests: ReadView.exists()
# ---------------------------------------------------------------------------
@pytest.mark.database
@pytest.mark.usefixtures("db")
class TestReadViewExists:
    def test_exists_true(self, test_domain, seeded_projections):
        view = test_domain.view_for(PersonProjection)
        assert view.exists("1") is True

    def test_exists_false(self, test_domain):
        view = test_domain.view_for(PersonProjection)
        assert view.exists("nonexistent") is False


# ---------------------------------------------------------------------------
# Tests: ReadView does not expose write methods
# ---------------------------------------------------------------------------
@pytest.mark.database
@pytest.mark.usefixtures("db")
class TestReadViewNoWriteAccess:
    def test_no_add_method(self, test_domain):
        view = test_domain.view_for(PersonProjection)
        assert not hasattr(view, "add")

    def test_no_dao_access(self, test_domain):
        view = test_domain.view_for(PersonProjection)
        assert not hasattr(view, "_dao")

    def test_no_delete_method(self, test_domain):
        view = test_domain.view_for(PersonProjection)
        assert not hasattr(view, "delete")

    def test_no_update_method(self, test_domain):
        view = test_domain.view_for(PersonProjection)
        assert not hasattr(view, "update")


# ---------------------------------------------------------------------------
# Tests: Cache-backed ReadView
# ---------------------------------------------------------------------------
class TestCacheBackedReadView:
    @pytest.fixture(autouse=True)
    def register_cached_projection(self, test_domain):
        test_domain.register(CachedPersonProjection, cache="default")
        test_domain.init(traverse=False)

    @pytest.fixture
    def seeded_cache(self, test_domain):
        cache = test_domain.cache_for(CachedPersonProjection)
        cache.add(
            CachedPersonProjection(person_id="1", first_name="John", last_name="Doe")
        )
        cache.add(
            CachedPersonProjection(person_id="2", first_name="Jane", last_name="Doe")
        )
        cache.add(
            CachedPersonProjection(person_id="3", first_name="Bob", last_name="Smith")
        )

    def test_get_by_identifier(self, test_domain, seeded_cache):
        view = test_domain.view_for(CachedPersonProjection)
        person = view.get("1")

        assert person.first_name == "John"
        assert person.last_name == "Doe"

    def test_get_nonexistent_raises_not_found(self, test_domain):
        view = test_domain.view_for(CachedPersonProjection)

        with pytest.raises(ObjectNotFoundError):
            view.get("nonexistent")

    def test_query_raises_not_supported(self, test_domain):
        view = test_domain.view_for(CachedPersonProjection)

        with pytest.raises(NotSupportedError, match="cache-backed"):
            view.query

    def test_find_by_raises_not_supported(self, test_domain):
        view = test_domain.view_for(CachedPersonProjection)

        with pytest.raises(NotSupportedError, match="cache-backed"):
            view.find_by(first_name="John")

    def test_count_all(self, test_domain, seeded_cache):
        view = test_domain.view_for(CachedPersonProjection)
        assert view.count() == 3

    def test_count_empty(self, test_domain):
        view = test_domain.view_for(CachedPersonProjection)
        assert view.count() == 0

    def test_exists_true(self, test_domain, seeded_cache):
        view = test_domain.view_for(CachedPersonProjection)
        assert view.exists("1") is True

    def test_exists_false(self, test_domain):
        view = test_domain.view_for(CachedPersonProjection)
        assert view.exists("nonexistent") is False

    def test_not_supported_messages_guide_user(self, test_domain):
        view = test_domain.view_for(CachedPersonProjection)

        with pytest.raises(NotSupportedError, match="get()"):
            view.query

        with pytest.raises(NotSupportedError, match="get()"):
            view.find_by(first_name="John")


# ---------------------------------------------------------------------------
# Tests: ReadView and repository_for coexistence
# ---------------------------------------------------------------------------
@pytest.mark.database
@pytest.mark.usefixtures("db")
class TestReadViewAndRepositoryCoexistence:
    def test_view_and_repo_see_same_data(self, test_domain, seeded_projections):
        """Data written via repository_for() is visible through view_for()."""
        view = test_domain.view_for(PersonProjection)
        person = view.get("1")
        assert person.first_name == "John"

    def test_view_query_and_repo_see_same_data(self, test_domain, seeded_projections):
        """view.query and repository query return the same results."""
        view = test_domain.view_for(PersonProjection)
        view_results = view.query.all()
        repo_results = test_domain.repository_for(PersonProjection).query.all()

        assert view_results.total == repo_results.total

    def test_repo_writes_visible_through_view(self, test_domain):
        """Adding data via repo, then reading through view."""
        repo = test_domain.repository_for(PersonProjection)
        repo.add(
            PersonProjection(
                person_id="99", first_name="New", last_name="Person", age=99
            )
        )

        view = test_domain.view_for(PersonProjection)
        person = view.get("99")
        assert person.first_name == "New"
        assert view.count() == 1
        assert view.exists("99") is True
