"""Tests for the query-shape assertion primitives.

The core logic runs against an in-process SQLite engine passed explicitly, so
these are plain core tests (no Docker, no adapter marker). Engine resolution
from the active domain and the no-op behaviour on non-SQLAlchemy backends are
covered separately.
"""

import pytest
from sqlalchemy import create_engine, text

from protean import Domain
from protean.core.aggregate import BaseAggregate
from protean.fields import Integer, String
from protean.integrations.pytest import (
    assert_no_overfetch,
    assert_no_subquery_wrap,
    assert_query_count,
)


@pytest.fixture
def engine():
    eng = create_engine("sqlite://")
    with eng.begin() as conn:
        conn.execute(text("CREATE TABLE t (id INTEGER, name VARCHAR)"))
        conn.execute(text("INSERT INTO t VALUES (1, 'a'), (2, 'b'), (3, 'c')"))
    yield eng
    eng.dispose()


class TestAssertQueryCount:
    def test_passes_on_exact_count(self, engine):
        with engine.connect() as conn:
            with assert_query_count(2, engine=engine):
                conn.execute(text("SELECT 1"))
                conn.execute(text("SELECT 2"))

    def test_fails_on_wrong_count(self, engine):
        with engine.connect() as conn:
            with pytest.raises(AssertionError, match=r"Expected 1 query, got 2"):
                with assert_query_count(1, engine=engine):
                    conn.execute(text("SELECT 1"))
                    conn.execute(text("SELECT 2"))

    def test_yields_captured_statements(self, engine):
        with engine.connect() as conn:
            with assert_query_count(1, engine=engine) as statements:
                conn.execute(text("SELECT 42"))
        assert any("SELECT 42" in s for s in statements)

    def test_does_not_swallow_block_exception(self, engine):
        # A failure inside the block propagates; the count is not asserted over it.
        with pytest.raises(ValueError):
            with assert_query_count(1, engine=engine):
                raise ValueError("boom")


class TestAssertNoSubqueryWrap:
    def test_passes_on_flat_count(self, engine):
        with engine.connect() as conn:
            with assert_no_subquery_wrap(engine=engine):
                conn.execute(text("SELECT count(*) FROM t"))

    def test_fails_on_subquery_wrapped_count(self, engine):
        with engine.connect() as conn:
            with pytest.raises(AssertionError, match=r"subquery-wrapped count"):
                with assert_no_subquery_wrap(engine=engine):
                    conn.execute(
                        text("SELECT count(*) FROM (SELECT id FROM t) AS anon_1")
                    )

    def test_plain_select_is_not_flagged(self, engine):
        with engine.connect() as conn:
            with assert_no_subquery_wrap(engine=engine):
                conn.execute(text("SELECT id FROM t"))


class TestAssertNoOverfetch:
    def test_passes_when_limit_within_ratio(self, engine):
        with engine.connect() as conn:
            with assert_no_overfetch(expected_returned=10, engine=engine):
                conn.execute(text("SELECT id FROM t LIMIT 10"))

    def test_fails_when_limit_exceeds_ratio(self, engine):
        with engine.connect() as conn:
            with pytest.raises(AssertionError, match=r"Over-fetch detected"):
                with assert_no_overfetch(expected_returned=10, engine=engine):
                    conn.execute(text("SELECT id FROM t LIMIT 100"))

    def test_ratio_is_configurable(self, engine):
        with engine.connect() as conn:
            # LIMIT 25 with expected 10 and ratio 3.0 -> threshold 30, passes.
            with assert_no_overfetch(expected_returned=10, ratio=3.0, engine=engine):
                conn.execute(text("SELECT id FROM t LIMIT 25"))

    def test_query_without_limit_is_ignored(self, engine):
        with engine.connect() as conn:
            with assert_no_overfetch(expected_returned=1, engine=engine):
                conn.execute(text("SELECT id FROM t"))

    def test_outer_limit_behind_smaller_inner_limit_is_caught(self, engine):
        # The inner subquery's LIMIT 5 must not mask the outer LIMIT 100.
        with engine.connect() as conn:
            with pytest.raises(AssertionError, match=r"Over-fetch detected"):
                with assert_no_overfetch(expected_returned=10, engine=engine):
                    conn.execute(
                        text("SELECT id FROM (SELECT id FROM t LIMIT 5) s LIMIT 100")
                    )


@pytest.mark.no_test_domain
class TestNoOpOnMemoryBackend:
    """With a memory-backed domain (no SQLAlchemy engine), the primitives are
    no-ops. A dedicated memory domain is built so the result does not depend on
    the ``--db`` the suite runs under."""

    @pytest.fixture
    def memory_domain(self):
        domain = Domain(name="QueryAssertionsMemory")
        domain.init(traverse=False)  # default provider is the in-memory adapter
        with domain.domain_context():
            yield domain

    def test_query_count_is_noop(self, memory_domain):
        with assert_query_count(999):
            pass

    def test_subquery_wrap_is_noop(self, memory_domain):
        with assert_no_subquery_wrap():
            pass

    def test_overfetch_is_noop(self, memory_domain):
        with assert_no_overfetch(expected_returned=1):
            pass


@pytest.mark.no_test_domain
class TestNoOpWithoutDomain:
    """With no domain bound at all, engine resolution degrades to a no-op
    rather than raising (the ``current_domain`` proxy resolves to ``None``)."""

    def test_query_count_is_noop_without_domain(self):
        with assert_query_count(999):
            pass

    def test_overfetch_is_noop_without_domain(self):
        with assert_no_overfetch(expected_returned=1):
            pass


class _Counter(BaseAggregate):
    name = String(max_length=50)
    value = Integer(default=0)


@pytest.mark.no_test_domain
class TestEngineResolutionFromDomain:
    """The engine is resolved from ``current_domain`` when not passed explicitly."""

    @pytest.fixture
    def sqlite_domain(self):
        domain = Domain(name="QueryAssertions")
        domain.config["databases"]["default"] = {
            "provider": "sqlite",
            "database_uri": "sqlite://",
        }
        domain.register(_Counter)
        domain.init(traverse=False)
        with domain.domain_context():
            provider = domain.providers["default"]
            domain.repository_for(_Counter)._dao  # register the table in metadata
            provider._metadata.create_all(provider._engine)
            yield domain

    def test_resolves_default_provider_engine(self, sqlite_domain):
        repo = sqlite_domain.repository_for(_Counter)
        repo.add(_Counter(name="a"))

        # No explicit engine: resolved from the active domain's default provider.
        # ``with_total=False`` keeps it to a single SELECT (no extra count query).
        with assert_query_count(1):
            repo._dao.query.filter(name="a").all(with_total=False)
