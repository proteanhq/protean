"""PostgreSQL coverage for ``SqlalchemyDAO._claim`` — the
``FOR UPDATE SKIP LOCKED`` fast path used by the outbox processing loop."""

import threading

import pytest

from protean.core.aggregate import BaseAggregate
from protean.fields import DateTime, Integer, String
from protean.utils.query import Q


class ClaimJob(BaseAggregate):
    status = String(max_length=20, default="ready")
    priority = Integer(default=0)
    locked_by = String(max_length=50)
    locked_until = DateTime()


@pytest.fixture
def claim_domain(test_domain):
    test_domain.register(ClaimJob)
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


def _seed(domain, count, status="ready"):
    repo = domain.repository_for(ClaimJob)
    for i in range(count):
        repo.add(ClaimJob(status=status, priority=i))


@pytest.mark.postgresql
class TestPostgresClaim:
    def test_claims_persist_and_skip_already_claimed(self, claim_domain):
        _seed(claim_domain, 5)
        dao = claim_domain.repository_for(ClaimJob)._dao

        claimed = dao._claim(
            Q(status="ready"),
            {"status": "claimed", "locked_by": "w1"},
            limit=10,
        )
        assert len(claimed) == 5
        assert all(j.status == "claimed" and j.locked_by == "w1" for j in claimed)

        # Durable, and a second claim finds nothing eligible.
        repo = claim_domain.repository_for(ClaimJob)
        for job in claimed:
            assert repo.get(job.id).status == "claimed"
        assert (
            dao._claim(
                Q(status="ready"), {"status": "claimed", "locked_by": "w2"}, limit=10
            )
            == []
        )

    def test_orders_and_limits(self, claim_domain):
        _seed(claim_domain, 6)
        dao = claim_domain.repository_for(ClaimJob)._dao

        claimed = dao._claim(
            Q(status="ready"),
            {"status": "claimed", "locked_by": "w1"},
            limit=3,
            order_by="-priority",
        )
        priorities = [j.priority for j in claimed]
        assert priorities == [5, 4, 3]

    def test_non_positive_limit_claims_nothing(self, claim_domain):
        _seed(claim_domain, 3)
        dao = claim_domain.repository_for(ClaimJob)._dao
        assert dao._claim(Q(status="ready"), {"status": "claimed"}, 0) == []

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
