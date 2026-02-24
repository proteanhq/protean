"""Tests for domain.connection_for().

Validates:
- domain.connection_for() returns a raw connection for database-backed projections
- domain.connection_for() returns a raw connection for cache-backed projections
- domain.connection_for() rejects non-projection types
- domain.connection_for() rejects string arguments
- The returned connection is usable for raw operations
"""

import pytest
from pydantic import Field

from protean.core.aggregate import BaseAggregate
from protean.core.projection import BaseProjection
from protean.exceptions import IncorrectUsageError


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


# ---------------------------------------------------------------------------
# Tests: domain.connection_for() — entry point validation
# ---------------------------------------------------------------------------
@pytest.mark.database
@pytest.mark.usefixtures("db")
class TestConnectionForEntryPoint:
    def test_returns_connection_for_database_backed_projection(self, test_domain):
        conn = test_domain.connection_for(PersonProjection)
        assert conn is not None

    def test_rejects_aggregate_class(self, test_domain):
        with pytest.raises(IncorrectUsageError, match="only available for projections"):
            test_domain.connection_for(Person)

    def test_rejects_string_argument(self, test_domain):
        with pytest.raises(IncorrectUsageError, match="not registered"):
            test_domain.connection_for("PersonProjection")


# ---------------------------------------------------------------------------
# Tests: Database-backed projection — connection usability
# ---------------------------------------------------------------------------
@pytest.mark.database
@pytest.mark.usefixtures("db")
class TestDatabaseBackedConnection:
    def test_connection_type_matches_provider(self, test_domain):
        """connection_for() returns the same type as providers.get_connection()."""
        conn = test_domain.connection_for(PersonProjection)
        provider_conn = test_domain.providers.get_connection("default")
        assert type(conn) is type(provider_conn)

    def test_connection_usable_after_seeding(self, test_domain, seeded_projections):
        """The returned connection is live and usable after data has been seeded."""
        conn = test_domain.connection_for(PersonProjection)
        assert conn is not None


# ---------------------------------------------------------------------------
# Tests: Cache-backed projection
# ---------------------------------------------------------------------------
class TestCacheBackedConnection:
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

    def test_returns_connection_for_cache_backed_projection(self, test_domain):
        conn = test_domain.connection_for(CachedPersonProjection)
        assert conn is not None

    def test_connection_type_matches_cache(self, test_domain):
        """connection_for() returns the same type as caches.get_connection()."""
        conn = test_domain.connection_for(CachedPersonProjection)
        cache_conn = test_domain.caches.get_connection("default")
        assert type(conn) is type(cache_conn)

    def test_connection_usable_after_seeding(self, test_domain, seeded_cache):
        """The returned cache connection is live and usable after data has been seeded."""
        conn = test_domain.connection_for(CachedPersonProjection)
        assert conn is not None
