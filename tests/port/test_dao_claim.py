"""Contract tests for ``BaseDAO._claim`` — the atomic find-and-claim
primitive that backs the outbox processing path.

These run against the in-memory adapter (core suite). The contract is:

- up to ``limit`` matching rows are selected, updated with ``claim_fields``,
  and returned reflecting the post-claim state;
- rows claimed by one caller are never handed to another (no double-claim);
- ordering and limit are honoured.

Adapter-specific fast paths (SQLAlchemy ``FOR UPDATE SKIP LOCKED``) are covered
separately under ``tests/adapters/repository/``.
"""

import threading

import pytest

from protean.core.aggregate import BaseAggregate
from protean.fields import DateTime, Integer, String
from protean.utils.query import Q


class Job(BaseAggregate):
    status = String(max_length=20, default="ready")
    priority = Integer(default=0)
    locked_by = String(max_length=50)
    locked_until = DateTime()


@pytest.fixture(autouse=True)
def setup(test_domain):
    test_domain.register(Job)
    test_domain.init(traverse=False)
    return test_domain


@pytest.fixture
def dao(test_domain):
    return test_domain.repository_for(Job)._dao


def _seed(test_domain, count, status="ready"):
    repo = test_domain.repository_for(Job)
    jobs = []
    for i in range(count):
        job = Job(status=status, priority=i)
        repo.add(job)
        jobs.append(job)
    return jobs


def _ready() -> Q:
    return Q(status="ready")


CLAIM = {"status": "claimed", "locked_by": "worker-A"}


class TestClaimContract:
    def test_claims_up_to_limit_and_returns_post_claim_state(self, test_domain, dao):
        _seed(test_domain, 5)

        claimed = dao._claim(_ready(), CLAIM, limit=3)

        assert len(claimed) == 3
        for job in claimed:
            assert job.status == "claimed"
            assert job.locked_by == "worker-A"

    def test_claim_is_persisted(self, test_domain, dao):
        _seed(test_domain, 2)

        claimed = dao._claim(_ready(), CLAIM, limit=10)
        assert len(claimed) == 2

        repo = test_domain.repository_for(Job)
        for job in claimed:
            assert repo.get(job.id).status == "claimed"

    def test_orders_by_key(self, test_domain, dao):
        _seed(test_domain, 5)

        claimed = dao._claim(_ready(), CLAIM, limit=3, order_by="-priority")

        priorities = [job.priority for job in claimed]
        assert priorities == sorted(priorities, reverse=True)

    def test_non_positive_limit_claims_nothing(self, test_domain, dao):
        _seed(test_domain, 3)

        assert dao._claim(_ready(), CLAIM, limit=0) == []
        assert dao._claim(_ready(), CLAIM, limit=-5) == []

    def test_second_claim_skips_already_claimed_rows(self, test_domain, dao):
        _seed(test_domain, 4)

        first = dao._claim(_ready(), CLAIM, limit=10)
        assert len(first) == 4

        # All rows are now ``claimed``; the eligibility criteria no longer match.
        second = dao._claim(_ready(), CLAIM, limit=10)
        assert second == []

    def test_only_matching_rows_are_claimed(self, test_domain, dao):
        _seed(test_domain, 2, status="ready")
        _seed(test_domain, 3, status="done")

        claimed = dao._claim(_ready(), CLAIM, limit=10)
        assert len(claimed) == 2
        assert all(job.status == "claimed" for job in claimed)

    def test_skips_rows_lost_to_a_concurrent_claimer(
        self, test_domain, dao, monkeypatch
    ):
        """When the guarded update claims zero rows (another worker won the row
        between the read and the write), that row is skipped, not returned."""
        _seed(test_domain, 2)

        # Force every guarded update to report "nothing claimed", simulating a
        # competing worker that grabbed each candidate first.
        monkeypatch.setattr(dao, "_update_all", lambda *args, **kwargs: 0)

        claimed = dao._claim(_ready(), CLAIM, limit=10)
        assert claimed == []


class TestClaimConcurrency:
    def test_no_double_claim_under_contention(self, test_domain):
        """Eight workers drain a pool of ready rows; every row is claimed by
        exactly one worker and none is claimed twice."""
        total = 40
        n_workers = 8
        _seed(test_domain, total)

        start = threading.Barrier(n_workers, timeout=10)
        results: dict[int, list] = {i: [] for i in range(n_workers)}

        def worker(idx: int) -> None:
            ctx = test_domain.domain_context()
            ctx.push()
            try:
                dao = test_domain.repository_for(Job)._dao
                start.wait()
                while True:
                    claimed = dao._claim(
                        Q(status="ready"),
                        {"status": "claimed", "locked_by": f"worker-{idx}"},
                        limit=3,
                    )
                    if not claimed:
                        break
                    results[idx].extend(job.id for job in claimed)
            finally:
                ctx.pop()

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(n_workers)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15)
            assert not t.is_alive(), "worker thread did not finish in time"

        all_ids = [job_id for ids in results.values() for job_id in ids]
        # Every ready row was claimed exactly once (no double-claim, no misses).
        assert len(all_ids) == total
        assert len(set(all_ids)) == total
