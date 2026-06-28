"""SQLite coverage for ``F`` column references.

The SQLAlchemy adapter resolves an ``F`` target to the referenced column, so a
filter renders as a SQL column-to-column predicate rather than a bind
parameter. These tests assert both the emitted SQL shape and the resulting
rows.
"""

import pytest

from protean import F
from protean.core.aggregate import BaseAggregate
from protean.fields import Integer, String
from protean.utils.query import Q


class FJob(BaseAggregate):
    name = String(max_length=50)
    retry_count = Integer(default=0)
    max_retries = Integer(default=3)
    ceiling = Integer()  # optional / nullable, for null-target coverage


@pytest.fixture
def f_domain(test_domain):
    test_domain.register(FJob)
    test_domain.init(traverse=False)
    test_domain.repository_for(FJob)._dao  # registers the table in metadata
    provider = test_domain.providers["default"]
    provider._metadata.create_all(provider._engine)
    yield test_domain


def _seed(domain):
    repo = domain.repository_for(FJob)
    repo.add(FJob(name="under", retry_count=1, max_retries=3))  # 1 < 3
    repo.add(FJob(name="equal", retry_count=3, max_retries=3))  # 3 < 3 false
    repo.add(FJob(name="over", retry_count=5, max_retries=2))  # 5 < 2 false


@pytest.mark.sqlite
class TestSqliteFExpression:
    def test_emitted_sql_references_the_column_not_a_bind_param(self, f_domain):
        dao = f_domain.repository_for(FJob)._dao
        expression = dao._build_filters(Q(retry_count__lt=F("max_retries")))
        sql = str(expression.compile(dialect=dao.provider._engine.dialect))

        # Both columns appear; the right-hand side is the column, not a bound
        # literal placeholder.
        assert "retry_count" in sql
        assert "max_retries" in sql
        assert ":max_retries" not in sql

    def test_filter_compares_two_columns(self, f_domain):
        _seed(f_domain)
        dao = f_domain.repository_for(FJob)._dao

        result = dao.query.filter(retry_count__lt=F("max_retries")).all()

        assert sorted(job.name for job in result.items) == ["under"]

    def test_gte_filter_compares_two_columns(self, f_domain):
        _seed(f_domain)
        dao = f_domain.repository_for(FJob)._dao

        result = dao.query.filter(retry_count__gte=F("max_retries")).all()

        assert sorted(job.name for job in result.items) == ["equal", "over"]

    def test_null_target_never_matches(self, f_domain):
        # SQL three-valued logic: comparing against a NULL column yields
        # UNKNOWN, so the row must not match — parity with the in-memory adapter.
        repo = f_domain.repository_for(FJob)
        repo.add(FJob(name="null_ceiling", retry_count=0))  # ceiling left NULL
        dao = f_domain.repository_for(FJob)._dao

        result = dao.query.filter(retry_count__lt=F("ceiling")).all()

        assert [job.name for job in result.items] == []
