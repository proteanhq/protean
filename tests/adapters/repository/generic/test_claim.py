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
import time

import pytest

from protean.core.aggregate import BaseAggregate
from protean.fields import Integer, String
from protean.port.dao import HoldBack
from protean.utils.query import Q


class ClaimJob(BaseAggregate):
    status: String(max_length=20, default="ready")
    priority: Integer(default=0)
    seq: Integer()
    locked_by: String(max_length=50)


class KeyedJob(BaseAggregate):
    status: String(max_length=20, default="ready")
    key: String(max_length=20)
    priority: Integer(default=0)
    seq: Integer(required=True)


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    # Its own table name: a local database can still hold a uuid-keyed
    # ``claim_job`` table that older checkouts of the PostgreSQL claim test
    # created and never dropped. Reusing it fails on psycopg 3.
    test_domain.register(ClaimJob, schema_name="generic_claim_job")
    test_domain.register(KeyedJob, schema_name="generic_keyed_job")
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

    def test_list_order_by_applies_every_key_in_its_direction(self, test_domain):
        repo = test_domain.repository_for(ClaimJob)
        # Inserted so that neither insertion order nor a priority-only sort
        # gives the expected result.
        for priority, seq in [(0, 2), (1, 1), (0, 0), (1, 0), (0, 1), (1, 2)]:
            repo.add(ClaimJob(priority=priority, seq=seq))
        dao = repo._dao

        claimed = dao._claim(
            Q(status="ready"),
            {"status": "claimed"},
            limit=10,
            order_by=["-priority", "seq"],
        )

        assert [(j.priority, j.seq) for j in claimed] == [
            (1, 0),
            (1, 1),
            (1, 2),
            (0, 0),
            (0, 1),
            (0, 2),
        ]

    def test_list_order_by_with_limit_claims_the_top_rows(self, test_domain):
        repo = test_domain.repository_for(ClaimJob)
        for priority, seq in [(0, 2), (1, 1), (0, 0), (1, 0), (0, 1), (1, 2)]:
            repo.add(ClaimJob(priority=priority, seq=seq))
        dao = repo._dao

        claimed = dao._claim(
            Q(status="ready"),
            {"status": "claimed"},
            limit=4,
            order_by=["-priority", "seq"],
        )

        assert [(j.priority, j.seq) for j in claimed] == [
            (1, 0),
            (1, 1),
            (1, 2),
            (0, 0),
        ]
        left = dao.query.filter(status="ready").all().items
        assert sorted((j.priority, j.seq) for j in left) == [(0, 1), (0, 2)]

    def test_null_sorts_first_on_a_descending_key(self, test_domain):
        repo = test_domain.repository_for(ClaimJob)
        for priority, seq in [(0, 1), (1, None), (0, None), (1, 2), (0, 2)]:
            repo.add(ClaimJob(priority=priority, seq=seq))
        dao = repo._dao
        expected = [(0, None), (1, None), (0, 2), (1, 2), (0, 1)]
        listed = (
            dao.query.filter(status="ready").order_by(["-seq", "priority"]).all().items
        )

        claimed = dao._claim(
            Q(status="ready"),
            {"status": "claimed"},
            limit=10,
            order_by=["-seq", "priority"],
        )

        assert [(j.priority, j.seq) for j in listed] == expected
        assert [(j.priority, j.seq) for j in claimed] == expected

    def test_null_sorts_last_on_an_ascending_key(self, test_domain):
        repo = test_domain.repository_for(ClaimJob)
        for priority, seq in [(1, None), (0, 1), (0, None), (1, 0)]:
            repo.add(ClaimJob(priority=priority, seq=seq))
        dao = repo._dao
        expected = [(1, 0), (0, 1), (0, None), (1, None)]
        listed = (
            dao.query.filter(status="ready").order_by(["seq", "priority"]).all().items
        )

        claimed = dao._claim(
            Q(status="ready"),
            {"status": "claimed"},
            limit=3,
            order_by=["seq", "priority"],
        )

        assert [(j.priority, j.seq) for j in listed] == expected
        assert [(j.priority, j.seq) for j in claimed] == expected[:3]

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


# A "ready" or "failed" row has not finished, and neither has one another call
# claimed, so all three hold the later rows of their key.
HOLD_BY_KEY = HoldBack(
    group_by=("key",),
    applies=Q(key__isnull=False),
    holds=Q(status__in=["ready", "failed", "claimed"]),
    order=("seq",),
)


def _keyed(test_domain, *rows: tuple[str, int, str | None, str]) -> None:
    """Add ``(label, seq, key, status)`` rows, using the label as the id."""
    repo = test_domain.repository_for(KeyedJob)
    for label, seq, key, status in rows:
        repo.add(KeyedJob(id=label, seq=seq, key=key, status=status))


def _skip_unless_postgresql(test_domain) -> None:
    dao = test_domain.repository_for(KeyedJob)._dao
    if dao.provider._engine.dialect.name != "postgresql":
        pytest.skip("the single-statement claim is PostgreSQL only")


def _claim_keyed(test_domain, hold_back=HOLD_BY_KEY, limit=10):
    dao = test_domain.repository_for(KeyedJob)._dao
    claimed = dao._claim(
        Q(status="ready"),
        {"status": "claimed"},
        limit=limit,
        order_by=["seq"],
        hold_back=hold_back,
    )
    return [job.id for job in claimed]


@pytest.mark.transactional
class TestClaimHoldBack:
    """``_claim`` with ``hold_back`` on any transactional adapter."""

    def test_without_hold_back_an_unfinished_earlier_row_holds_nothing(
        self, test_domain
    ):
        _keyed(test_domain, ("b", 1, "k1", "ready"), ("a", 0, "k1", "failed"))

        assert _claim_keyed(test_domain, hold_back=None) == ["b"]

    def test_an_earlier_row_outside_the_criteria_holds_the_later_row(self, test_domain):
        _keyed(test_domain, ("b", 1, "k1", "ready"), ("a", 0, "k1", "failed"))

        assert _claim_keyed(test_domain) == []

    def test_a_finished_earlier_row_holds_nothing(self, test_domain):
        _keyed(test_domain, ("b", 1, "k1", "ready"), ("a", 0, "k1", "done"))

        assert _claim_keyed(test_domain) == ["b"]

    def test_rows_of_one_key_are_claimed_together(self, test_domain):
        _keyed(
            test_domain,
            ("c", 2, "k1", "ready"),
            ("b", 1, "k1", "ready"),
            ("a", 0, "k1", "ready"),
        )

        assert _claim_keyed(test_domain) == ["a", "b", "c"]

    def test_a_row_claimed_by_an_earlier_call_holds_the_later_row(self, test_domain):
        _keyed(test_domain, ("a", 0, "k1", "ready"))
        assert _claim_keyed(test_domain) == ["a"]
        _keyed(test_domain, ("b", 1, "k1", "ready"))

        assert _claim_keyed(test_domain) == []

    def test_other_keys_and_ungrouped_rows_keep_flowing(self, test_domain):
        _keyed(
            test_domain,
            ("k1-b", 1, "k1", "ready"),
            ("k1-a", 0, "k1", "failed"),
            ("k2-a", 2, "k2", "ready"),
            ("none-a", 3, None, "ready"),
        )

        assert _claim_keyed(test_domain) == ["k2-a", "none-a"]

    def test_a_held_backlog_larger_than_the_limit_does_not_starve_other_keys(
        self, test_domain
    ):
        _keyed(test_domain, ("k1-0", 0, "k1", "failed"))
        _keyed(test_domain, *[(f"k1-{n}", n, "k1", "ready") for n in range(1, 6)])
        _keyed(test_domain, *[(f"k2-{n}", 10 + n, "k2", "ready") for n in range(2)])

        assert _claim_keyed(test_domain, limit=2) == ["k2-0", "k2-1"]

    def test_rows_in_different_lanes_never_hold_each_other(self, test_domain):
        hold_back = HoldBack(
            group_by=HOLD_BY_KEY.group_by,
            applies=HOLD_BY_KEY.applies,
            holds=HOLD_BY_KEY.holds,
            order=HOLD_BY_KEY.order,
            lanes=(Q(priority__gte=5), Q(priority__lt=5)),
        )
        repo = test_domain.repository_for(KeyedJob)
        repo.add(KeyedJob(id="low-a", seq=0, key="k1", priority=0, status="failed"))
        repo.add(KeyedJob(id="low-b", seq=1, key="k1", priority=0))
        repo.add(KeyedJob(id="high-b", seq=2, key="k1", priority=10))

        assert _claim_keyed(test_domain, hold_back=hold_back) == ["high-b"]


@pytest.mark.atomic_transactions
class TestClaimHoldBackUnderContention:
    """Two workers on separate connections never take a key's rows out of
    order on PostgreSQL's single-statement claim.

    The portable claim on other databases reads and updates in separate
    statements, so it makes no such promise under contention.
    """

    def test_a_row_another_connection_is_claiming_holds_the_later_row(
        self, test_domain
    ):
        _skip_unless_postgresql(test_domain)
        _keyed(test_domain, ("a", 0, "k1", "ready"), ("b", 1, "k1", "ready"))
        dao = test_domain.repository_for(KeyedJob)._dao

        # Worker 1 locks "a" in an open transaction on its own connection.
        engine = dao.provider._engine
        with engine.connect() as conn:
            with conn.begin():
                table = dao.database_model_cls.__table__
                conn.execute(
                    table.select().where(table.c.id == "a").with_for_update()
                ).all()

                # Worker 2 skips the locked "a" and must not take "b".
                result: list[list[str]] = []

                def worker() -> None:
                    ctx = test_domain.domain_context()
                    ctx.push()
                    try:
                        result.append(_claim_keyed(test_domain))
                    finally:
                        ctx.pop()

                thread = threading.Thread(target=worker)
                thread.start()
                thread.join(timeout=20)
                assert not thread.is_alive()

        assert result == [[]]

    def test_no_row_is_claimed_before_its_earlier_rows_finish(self, test_domain):
        _skip_unless_postgresql(test_domain)
        keys = ("k1", "k2", "k3")
        per_key = 8
        _keyed(
            test_domain,
            *[
                (f"{key}-{n}", n * len(keys) + i, key, "ready")
                for n in range(per_key)
                for i, key in enumerate(keys)
            ],
        )

        n_workers = 2
        start = threading.Barrier(n_workers, timeout=15)
        done: set[str] = set()
        out_of_order: list[str] = []
        lock = threading.Lock()
        errors: list[Exception] = []

        def worker(idx: int) -> None:
            ctx = test_domain.domain_context()
            ctx.push()
            try:
                repo = test_domain.repository_for(KeyedJob)
                dao = repo._dao
                start.wait()
                idle = 0
                while idle < 50:
                    claimed = dao._claim(
                        Q(status="ready"),
                        {"status": "claimed"},
                        limit=2,
                        order_by=["seq"],
                        hold_back=HOLD_BY_KEY,
                    )
                    if not claimed:
                        idle += 1
                        time.sleep(0.005)
                        continue
                    idle = 0
                    claimed_ids = {job.id for job in claimed}
                    with lock:
                        for job in claimed:
                            key, n = job.id.rsplit("-", 1)
                            earlier = {f"{key}-{m}" for m in range(int(n))}
                            if earlier - done - claimed_ids:
                                out_of_order.append(job.id)
                    # Hold the claim open so the other worker tries to claim
                    # while these rows are still unfinished.
                    time.sleep(0.02)
                    for job in claimed:
                        # Recorded before the commit, so a claim that already
                        # sees the row finished never finds it missing here.
                        with lock:
                            done.add(job.id)
                        fresh = repo.get(job.id)
                        fresh.status = "done"
                        repo.add(fresh)
            except Exception as exc:
                errors.append(exc)
            finally:
                ctx.pop()

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(n_workers)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
            assert not t.is_alive()

        assert not errors, f"worker(s) raised during claim: {errors}"
        assert len(done) == len(keys) * per_key
        assert out_of_order == []
