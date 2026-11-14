"""PostgreSQL coverage for ``SADAO.claim``, the ``FOR UPDATE SKIP LOCKED``
single-statement claim that ``_claim`` runs because the PostgreSQL provider
declares ``NATIVE_CLAIM``. The claim contract itself is covered by the generic
claim tests."""

import threading

import pytest

from protean.core.aggregate import BaseAggregate
from protean.fields import DateTime, Integer, String
from protean.integrations.pytest import assert_query_count
from protean.port.dao import HoldBack
from protean.utils.query import Q


class ClaimJob(BaseAggregate):
    status = String(max_length=20, default="ready")
    priority = Integer(default=0)
    locked_by = String(max_length=50)
    locked_until = DateTime()


@pytest.fixture
def claim_domain(test_domain):
    # Its own table name: this module leaves the table in place, and its uuid
    # identity would otherwise be reused by the generic claim tests, which map
    # a string identity onto their own table.
    test_domain.register(ClaimJob, schema_name="pg_claim_job")
    test_domain.init(traverse=False)
    # Accessing the DAO registers ClaimJob's table in the provider metadata,
    # which must happen before create_all(). create_all is idempotent; the
    # autouse data-reset fixture clears rows between tests, so the table is left
    # in place (dropping it here would race that reset's DELETE).
    dao = test_domain.repository_for(ClaimJob)._dao
    provider = test_domain.providers["default"]
    provider._metadata.create_all(provider._engine)
    # Start each test from a clean slate — rows persist across tests in this
    # module (the table is shared and not dropped between tests).
    dao._delete_all()
    yield test_domain


class KeyedClaimJob(BaseAggregate):
    status = String(max_length=20, default="ready")
    key = String(max_length=20)
    seq = Integer(required=True)


@pytest.fixture
def keyed_claim_domain(test_domain):
    test_domain.register(KeyedClaimJob, schema_name="pg_keyed_claim_job")
    test_domain.init(traverse=False)
    dao = test_domain.repository_for(KeyedClaimJob)._dao
    provider = test_domain.providers["default"]
    provider._metadata.create_all(provider._engine)
    dao._delete_all()
    yield test_domain


def _seed(domain, count, status="ready"):
    repo = domain.repository_for(ClaimJob)
    for i in range(count):
        repo.add(ClaimJob(status=status, priority=i))


@pytest.mark.postgresql
class TestPostgresClaim:
    def test_claim_is_one_update_returning_statement(self, claim_domain):
        """PostgreSQL declares ``NATIVE_CLAIM``, so a claim is a single
        ``UPDATE ... RETURNING`` round trip."""
        _seed(claim_domain, 4)
        dao = claim_domain.repository_for(ClaimJob)._dao
        engine = claim_domain.providers["default"]._engine

        with assert_query_count(1, engine) as statements:
            claimed = dao._claim(
                Q(status="ready"),
                {"status": "claimed", "locked_by": "w1"},
                limit=2,
                order_by="-priority",
            )

        assert [j.priority for j in claimed] == [3, 2]
        assert "UPDATE" in statements[0]
        assert "RETURNING" in statements[0]

    def test_held_back_claim_is_one_update_returning_statement(
        self, keyed_claim_domain
    ):
        """With ``hold_back``, the claim is still one statement: the held key's
        rows are left out inside it, with no page reads before it."""
        repo = keyed_claim_domain.repository_for(KeyedClaimJob)
        repo.add(KeyedClaimJob(key="k1", seq=0, status="failed"))
        repo.add(KeyedClaimJob(key="k1", seq=1))
        repo.add(KeyedClaimJob(key="k2", seq=2))
        dao = repo._dao
        engine = keyed_claim_domain.providers["default"]._engine

        with assert_query_count(1, engine) as statements:
            claimed = dao._claim(
                Q(status="ready"),
                {"status": "claimed"},
                limit=10,
                order_by=["seq"],
                hold_back=HoldBack(
                    group_by=("key",),
                    applies=Q(key__isnull=False),
                    holds=Q(status__in=["ready", "claimed", "failed"]),
                    order=("seq",),
                    lane_of=lambda row: None if row.key is None else 0,
                ),
            )

        assert [(j.key, j.seq) for j in claimed] == [("k2", 2)]
        assert "UPDATE" in statements[0]
        assert "RETURNING" in statements[0]

    def test_skip_locked_prevents_double_claim_under_contention(self, claim_domain):
        """Two workers drain the pool concurrently; ``SKIP LOCKED`` ensures
        each row is claimed exactly once with no blocking."""
        total = 20
        _seed(claim_domain, total)

        n_workers = 2  # postgres test pool is small (pool_size=1, overflow=2)
        start = threading.Barrier(n_workers, timeout=15)
        results: dict[int, list] = {i: [] for i in range(n_workers)}

        def worker(idx: int) -> None:
            ctx = claim_domain.domain_context()
            ctx.push()
            try:
                dao = claim_domain.repository_for(ClaimJob)._dao
                start.wait()
                while True:
                    claimed = dao._claim(
                        Q(status="ready"),
                        {"status": "claimed", "locked_by": f"w{idx}"},
                        limit=3,
                    )
                    if not claimed:
                        break
                    results[idx].extend(j.id for j in claimed)
            finally:
                ctx.pop()

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(n_workers)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=20)
            assert not t.is_alive()

        all_ids = [jid for ids in results.values() for jid in ids]
        assert len(all_ids) == total
        assert len(set(all_ids)) == total
