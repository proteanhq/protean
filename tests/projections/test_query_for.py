"""Tests for domain.view_for().query and ReadOnlyQuerySet.

Validates:
- ReadOnlyQuerySet blocks all mutation operations with NotSupportedError
- ReadOnlyQuerySet preserves all read operations (filter, exclude, order_by, etc.)
- Chained operations on ReadOnlyQuerySet preserve the type
- domain.view_for().query returns ReadOnlyQuerySet for projections
- Filtering, ordering, pagination work through the API
- Backward compatibility: domain.repository_for(Projection) still works
"""

import pytest
from pydantic import Field

from protean.core.aggregate import BaseAggregate
from protean.core.projection import BaseProjection
from protean.core.queryset import ReadOnlyQuerySet
from protean.exceptions import NotSupportedError


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


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(PersonProjection)
    test_domain.register(Person)
    test_domain.init(traverse=False)


# ---------------------------------------------------------------------------
# Helper: seed projection data
# ---------------------------------------------------------------------------
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
# Tests: ReadOnlyQuerySet — mutation blocking
# ---------------------------------------------------------------------------
@pytest.mark.database
@pytest.mark.usefixtures("db")
class TestReadOnlyQuerySetMutationBlocking:
    def test_update_raises_not_supported(self, test_domain):
        qs = test_domain.view_for(PersonProjection).query

        with pytest.raises(NotSupportedError, match="Updates are not allowed"):
            qs.update(first_name="X")

    def test_delete_raises_not_supported(self, test_domain):
        qs = test_domain.view_for(PersonProjection).query

        with pytest.raises(NotSupportedError, match="Deletes are not allowed"):
            qs.delete()

    def test_update_all_raises_not_supported(self, test_domain):
        qs = test_domain.view_for(PersonProjection).query

        with pytest.raises(NotSupportedError, match="Bulk updates are not allowed"):
            qs.update_all(first_name="X")

    def test_delete_all_raises_not_supported(self, test_domain):
        qs = test_domain.view_for(PersonProjection).query

        with pytest.raises(NotSupportedError, match="Bulk deletes are not allowed"):
            qs.delete_all()

    def test_error_messages_guide_user(self, test_domain):
        qs = test_domain.view_for(PersonProjection).query

        with pytest.raises(NotSupportedError, match="domain.repository_for"):
            qs.update(first_name="X")

        with pytest.raises(NotSupportedError, match="domain.repository_for"):
            qs.delete()

        with pytest.raises(NotSupportedError, match="domain.repository_for"):
            qs.update_all(first_name="X")

        with pytest.raises(NotSupportedError, match="domain.repository_for"):
            qs.delete_all()


# ---------------------------------------------------------------------------
# Tests: ReadOnlyQuerySet — type preservation through chaining
# ---------------------------------------------------------------------------
@pytest.mark.database
@pytest.mark.usefixtures("db")
class TestReadOnlyQuerySetChaining:
    def test_filter_returns_read_only_queryset(self, test_domain):
        qs = test_domain.view_for(PersonProjection).query.filter(last_name="Doe")
        assert isinstance(qs, ReadOnlyQuerySet)

    def test_exclude_returns_read_only_queryset(self, test_domain):
        qs = test_domain.view_for(PersonProjection).query.exclude(last_name="Doe")
        assert isinstance(qs, ReadOnlyQuerySet)

    def test_order_by_returns_read_only_queryset(self, test_domain):
        qs = test_domain.view_for(PersonProjection).query.order_by("age")
        assert isinstance(qs, ReadOnlyQuerySet)

    def test_limit_returns_read_only_queryset(self, test_domain):
        qs = test_domain.view_for(PersonProjection).query.limit(10)
        assert isinstance(qs, ReadOnlyQuerySet)

    def test_offset_returns_read_only_queryset(self, test_domain):
        qs = test_domain.view_for(PersonProjection).query.offset(5)
        assert isinstance(qs, ReadOnlyQuerySet)

    def test_deeply_chained_remains_read_only(self, test_domain):
        qs = (
            test_domain.view_for(PersonProjection)
            .query.filter(last_name="Doe")
            .exclude(age=3)
            .order_by("-age")
            .limit(10)
            .offset(0)
        )
        assert isinstance(qs, ReadOnlyQuerySet)

    def test_chained_mutation_still_blocked(self, test_domain):
        qs = test_domain.view_for(PersonProjection).query.filter(last_name="Doe")

        with pytest.raises(NotSupportedError):
            qs.update(first_name="X")

        with pytest.raises(NotSupportedError):
            qs.delete()


# ---------------------------------------------------------------------------
# Tests: domain.view_for().query — entry point
# ---------------------------------------------------------------------------
@pytest.mark.database
@pytest.mark.usefixtures("db")
class TestViewForQuery:
    def test_returns_read_only_queryset(self, test_domain):
        qs = test_domain.view_for(PersonProjection).query
        assert isinstance(qs, ReadOnlyQuerySet)

    def test_filter_and_all(self, test_domain, seeded_projections):
        results = (
            test_domain.view_for(PersonProjection).query.filter(last_name="Doe").all()
        )

        assert results.total == 3
        names = {item.first_name for item in results}
        assert names == {"John", "Jane", "Baby"}

    def test_exclude(self, test_domain, seeded_projections):
        results = (
            test_domain.view_for(PersonProjection).query.exclude(last_name="Doe").all()
        )

        assert results.total == 1
        assert results.first.first_name == "Bob"

    def test_order_by(self, test_domain, seeded_projections):
        results = test_domain.view_for(PersonProjection).query.order_by("age").all()

        ages = [item.age for item in results]
        assert ages == [3, 25, 36, 38]

    def test_order_by_descending(self, test_domain, seeded_projections):
        results = test_domain.view_for(PersonProjection).query.order_by("-age").all()

        ages = [item.age for item in results]
        assert ages == [38, 36, 25, 3]

    def test_limit_and_offset(self, test_domain, seeded_projections):
        results = (
            test_domain.view_for(PersonProjection)
            .query.order_by("age")
            .limit(2)
            .offset(1)
            .all()
        )

        assert len(results.items) == 2
        ages = [item.age for item in results]
        assert ages == [25, 36]

    def test_result_set_properties(self, test_domain, seeded_projections):
        results = (
            test_domain.view_for(PersonProjection).query.order_by("age").limit(2).all()
        )

        assert results.total == 4
        assert len(results.items) == 2
        assert results.first.age == 3
        assert results.last.age == 25
        assert results.has_next is True
        assert results.has_prev is False

    def test_iteration(self, test_domain, seeded_projections):
        names = []
        for item in test_domain.view_for(PersonProjection).query.filter(
            last_name="Doe"
        ):
            names.append(item.first_name)

        assert len(names) == 3
        assert set(names) == {"John", "Jane", "Baby"}

    def test_empty_result(self, test_domain):
        results = (
            test_domain.view_for(PersonProjection)
            .query.filter(last_name="Nonexistent")
            .all()
        )

        assert results.total == 0
        assert results.items == []
        assert results.first is None
        assert results.last is None


# ---------------------------------------------------------------------------
# Tests: Backward compatibility
# ---------------------------------------------------------------------------
@pytest.mark.database
@pytest.mark.usefixtures("db")
class TestBackwardCompatibility:
    def test_repository_for_still_works(self, test_domain):
        """domain.repository_for(Projection) continues to work unchanged."""
        repo = test_domain.repository_for(PersonProjection)
        person = PersonProjection(person_id="1", first_name="John", last_name="Doe")
        repo.add(person)

        refreshed = repo.get("1")
        assert refreshed.first_name == "John"

    def test_repository_for_allows_mutations(self, test_domain):
        """Mutations through repository_for() are not affected."""
        repo = test_domain.repository_for(PersonProjection)
        repo.add(PersonProjection(person_id="1", first_name="John", last_name="Doe"))
        repo.add(PersonProjection(person_id="2", first_name="Jane", last_name="Doe"))

        # Mutation through repository query still works
        count = repo.query.filter(last_name="Doe").delete()
        assert count == 2

    def test_view_for_and_repository_for_see_same_data(
        self, test_domain, seeded_projections
    ):
        """view_for().query and repository_for() query the same backing store."""
        view_results = test_domain.view_for(PersonProjection).query.all()
        repo_results = test_domain.repository_for(PersonProjection).query.all()

        assert view_results.total == repo_results.total
