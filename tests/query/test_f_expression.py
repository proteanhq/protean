"""Unit tests for ``F`` column references inside ``Q`` lookups.

The behavioural filtering tests run against the in-memory adapter (no marker);
SQLAlchemy and Elasticsearch behaviour live beside those adapters' suites.
"""

import pytest

from protean import F
from protean.core.aggregate import BaseAggregate
from protean.fields import Integer, String
from protean.utils.query import F as QueryF


class Job(BaseAggregate):
    name: String(max_length=50)
    retry_count: Integer(default=0)
    max_retries: Integer(default=3)
    ceiling: Integer()  # optional / nullable, for null-target coverage


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Job)
    test_domain.init(traverse=False)


@pytest.fixture
def repo(test_domain):
    return test_domain.repository_for(Job)


class TestFClass:
    """The ``F`` value type itself."""

    def test_exported_from_package_root(self):
        assert F is QueryF

    def test_repr_round_trips_the_name(self):
        assert repr(F("max_retries")) == "F('max_retries')"

    def test_equality_is_by_name(self):
        assert F("max_retries") == F("max_retries")
        assert F("max_retries") != F("retry_count")
        assert F("max_retries") != "max_retries"

    def test_hashable_and_consistent_with_equality(self):
        assert hash(F("max_retries")) == hash(F("max_retries"))
        assert {F("a"), F("a"), F("b")} == {F("a"), F("b")}

    def test_is_immutable(self):
        f = F("max_retries")
        with pytest.raises(AttributeError):
            f.other = "x"  # __slots__ forbids new attributes


class TestFInMemoryFilter:
    """Column-to-column comparisons evaluated by the in-memory adapter."""

    @pytest.fixture(autouse=True)
    def seed(self, repo):
        repo.add(Job(name="under", retry_count=1, max_retries=3))  # 1 < 3
        repo.add(Job(name="equal", retry_count=3, max_retries=3))  # 3 < 3 false
        repo.add(Job(name="over", retry_count=5, max_retries=2))  # 5 < 2 false
        return repo

    def _names(self, result):
        return sorted(job.name for job in result.items)

    def test_lt_compares_two_columns(self, repo):
        result = repo._dao.query.filter(retry_count__lt=F("max_retries")).all()
        assert self._names(result) == ["under"]

    def test_gte_compares_two_columns(self, repo):
        result = repo._dao.query.filter(retry_count__gte=F("max_retries")).all()
        assert self._names(result) == ["equal", "over"]

    def test_exact_compares_two_columns(self, repo):
        result = repo._dao.query.filter(retry_count=F("max_retries")).all()
        assert self._names(result) == ["equal"]

    def test_null_target_never_matches(self, repo):
        # A row whose F-referenced column is NULL is UNKNOWN in SQL and must
        # not match the comparison (``ceiling`` is left null here).
        repo.add(Job(name="null_ceiling", retry_count=0))
        result = repo._dao.query.filter(retry_count__lt=F("ceiling")).all()
        assert self._names(result) == []
