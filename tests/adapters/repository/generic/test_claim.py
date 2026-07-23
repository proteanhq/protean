"""Generic find-and-claim conformance tests across database providers.

``_claim`` correctness (single worker) runs on every transactional adapter
(in-memory + SQL). No-double-claim under concurrency requires real
database-level atomicity, so it runs on SQL only (``atomic_transactions``).

Elasticsearch is exempt from ``_claim`` conformance: it has neither the
``transactional`` nor the ``atomic_transactions`` capability, and its
document-versioning surfaces a lost race as a version conflict rather than a
graceful skip, so it is not a supported concurrent claim store. See ADR-0013
(claim contract) and ADR-0023 (conformance tiers).
"""

import threading

import pytest

from protean.core.aggregate import BaseAggregate
from protean.fields import Integer, String
from protean.utils.query import Q


class ClaimJob(BaseAggregate):
    status: String(max_length=20, default="ready")
    priority: Integer(default=0)
    locked_by: String(max_length=50)


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(ClaimJob)
    test_domain.init(traverse=False)


def _seed(test_domain, count, status="ready"):
    repo = test_domain.repository_for(ClaimJob)
    for i in range(count):
        repo.add(ClaimJob(status=status, priority=i))


@pytest.mark.transactional
class TestClaimConformance:
    """``_claim`` correctness for any transactional adapter (in-memory + SQL)."""

    def test_claimed_rows_return_in_post_claim_state(self, test_domain):
        _seed(test_domain, 5)
        dao = test_domain.repository_for(ClaimJob)._dao

        claimed = dao._claim(
            Q(status="ready"),
            {"status": "claimed", "locked_by": "w1"},
            limit=10,
        )

        assert len(claimed) == 5
        assert all(j.status == "claimed" and j.locked_by == "w1" for j in claimed)

    def test_claim_is_durable_and_second_claim_finds_nothing(self, test_domain):
        _seed(test_domain, 3)
        repo = test_domain.repository_for(ClaimJob)
        dao = repo._dao

        claimed = dao._claim(Q(status="ready"), {"status": "claimed"}, limit=10)
        assert len(claimed) == 3

        # The claim is committed the moment ``_claim`` returns.
        for job in claimed:
            assert repo.get(job.id).status == "claimed"

        # No eligible rows remain, so a second worker claims nothing.
        assert dao._claim(Q(status="ready"), {"status": "claimed"}, limit=10) == []

    def test_criteria_restricts_eligible_rows(self, test_domain):
        # Seed a mix: only the "ready" rows satisfy the claim criteria.
        _seed(test_domain, 3, status="ready")
        _seed(test_domain, 2, status="done")
        dao = test_domain.repository_for(ClaimJob)._dao

        claimed = dao._claim(Q(status="ready"), {"status": "claimed"}, limit=10)

        assert len(claimed) == 3
        assert all(j.status == "claimed" for j in claimed)
        # The never-eligible "done" rows are left untouched.
        assert dao.query.filter(status="done").count() == 2

    def test_limit_and_order_by_select_the_top_rows(self, test_domain):
        _seed(test_domain, 6)
        dao = test_domain.repository_for(ClaimJob)._dao

        claimed = dao._claim(
            Q(status="ready"),
            {"status": "claimed"},
            limit=3,
            order_by="-priority",
        )

        assert [j.priority for j in claimed] == [5, 4, 3]

    def test_non_positive_limit_claims_nothing(self, test_domain):
        _seed(test_domain, 3)
        dao = test_domain.repository_for(ClaimJob)._dao

        assert dao._claim(Q(status="ready"), {"status": "claimed"}, 0) == []
        assert dao._claim(Q(status="ready"), {"status": "claimed"}, -1) == []
        # A non-positive limit is a no-op: no row was mutated.
        assert dao.query.filter(status="ready").count() == 3


@pytest.mark.atomic_transactions
class TestClaimNoDoubleClaim:
    """No two workers ever claim the same row.

    Requires real database-level atomicity, so this runs on SQL adapters only
    (``atomic_transactions``): PostgreSQL, SQLite, and MSSQL. Each upholds
    no-double-claim by its own mechanism — ``FOR UPDATE SKIP LOCKED`` (the
    PostgreSQL fast path), serialized writers (SQLite), or the portable guarded
    ``UPDATE ... WHERE`` re-evaluated under row-lock contention (MSSQL) — so
    each seeded row is claimed exactly once.
    """

    def test_no_double_claim_under_contention(self, test_domain):
        total = 20
        _seed(test_domain, total)

        n_workers = 2  # SQL test pools are small (e.g. pool_size=1, overflow=2)
        start = threading.Barrier(n_workers, timeout=15)
        results: dict[int, list] = {i: [] for i in range(n_workers)}
        errors: list[Exception] = []

        def worker(idx: int) -> None:
            ctx = test_domain.domain_context()
            ctx.push()
            try:
                dao = test_domain.repository_for(ClaimJob)._dao
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
            except Exception as exc:
                errors.append(exc)
            finally:
                ctx.pop()

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(n_workers)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=20)
            assert not t.is_alive()

        # A worker that died by raising would otherwise leave the other to drain
        # every row, masking the crash behind a green count — surface it.
        assert not errors, f"worker(s) raised during claim: {errors}"

        all_ids = [jid for ids in results.values() for jid in ids]
        # Every row claimed, and none claimed twice.
        assert len(all_ids) == total
        assert len(set(all_ids)) == total
