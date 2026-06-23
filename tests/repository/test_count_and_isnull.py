"""Cross-adapter tests for ``QuerySet.count()`` and ``__isnull`` lookup.

These tests are marker-gated so they exercise SQLAlchemy (Postgres/SQLite/MSSQL)
and Elasticsearch backends in addition to the in-memory default. The same
behaviors are also covered against memory in ``tests/query/test_queryset.py``.
"""

import pytest

from protean.core.aggregate import BaseAggregate
from protean.fields import Integer, String


class Member(BaseAggregate):
    first_name: String(max_length=50, required=True)
    last_name: String(max_length=50, required=True)
    age: Integer(default=21)
    nickname: String(max_length=50)  # nullable — not required, no default


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Member)
    test_domain.init(traverse=False)


@pytest.mark.basic_storage
@pytest.mark.usefixtures("db")
class TestQuerySetCountAcrossAdapters:
    """``count()`` returns adapter-agnostic integer totals."""

    def _seed(self, test_domain):
        repo = test_domain.repository_for(Member)
        repo.add(Member(first_name="Alice", last_name="Wonder", age=30))
        repo.add(Member(first_name="Bob", last_name="Wonder", age=40))
        repo.add(Member(first_name="Carol", last_name="Other", age=25))

    def test_count_on_empty_repository_is_zero(self, test_domain):
        assert test_domain.repository_for(Member).query.count() == 0

    def test_count_returns_total(self, test_domain):
        self._seed(test_domain)
        assert test_domain.repository_for(Member).query.count() == 3

    def test_count_with_filter(self, test_domain):
        self._seed(test_domain)
        repo = test_domain.repository_for(Member)
        assert repo.query.filter(last_name="Wonder").count() == 2
        assert repo.query.filter(age__gte=30).count() == 2

    def test_count_with_combined_criteria(self, test_domain):
        self._seed(test_domain)
        repo = test_domain.repository_for(Member)
        assert repo.query.filter(last_name="Wonder", age__gte=35).count() == 1


@pytest.mark.basic_storage
@pytest.mark.usefixtures("db")
class TestIsNullLookupAcrossAdapters:
    """``__isnull`` matches null/non-null rows correctly."""

    def _seed(self, test_domain):
        repo = test_domain.repository_for(Member)
        # Alice has nickname; Bob and Carol do not.
        repo.add(Member(first_name="Alice", last_name="Wonder", age=30, nickname="Ace"))
        repo.add(Member(first_name="Bob", last_name="Wonder", age=40))
        repo.add(Member(first_name="Carol", last_name="Other", age=25))

    def test_isnull_true_returns_rows_with_null_field(self, test_domain):
        self._seed(test_domain)
        repo = test_domain.repository_for(Member)
        assert repo.query.filter(nickname__isnull=True).count() == 2

    def test_isnull_false_returns_rows_with_non_null_field(self, test_domain):
        self._seed(test_domain)
        repo = test_domain.repository_for(Member)
        result = repo.query.filter(nickname__isnull=False).all().items
        assert len(result) == 1
        assert result[0].nickname == "Ace"

    def test_isnull_combined_with_other_predicates(self, test_domain):
        self._seed(test_domain)
        repo = test_domain.repository_for(Member)
        # Bob has null nickname AND age >= 35.
        result = repo.query.filter(nickname__isnull=True, age__gte=35).all().items
        assert len(result) == 1
        assert result[0].first_name == "Bob"
