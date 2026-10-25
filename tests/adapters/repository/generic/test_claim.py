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
    lane_of=lambda row: None if row.key is None else 0,
)

# The same grouping, split into a high-priority lane and a low-priority one.
HOLD_BY_KEY_AND_LANE = HoldBack(
    group_by=HOLD_BY_KEY.group_by,
    applies=HOLD_BY_KEY.applies,
    holds=HOLD_BY_KEY.holds,
    order=HOLD_BY_KEY.order,
    lane_of=lambda row: None if row.key is None else int(row.priority < 5),
    lanes=(Q(priority__gte=5), Q(priority__lt=5)),
)


def _row(
    label: str, seq: int, key: str | None, status: str = "ready", priority: int = 0
) -> tuple[str, int, str | None, str, int]:
    return (label, seq, key, status, priority)


def _keyed(test_domain, *rows: tuple[str, int, str | None, str, int]) -> None:
    """Add ``(label, seq, key, status, priority)`` rows, using the label as
    the id."""
    repo = test_domain.repository_for(KeyedJob)
    for label, seq, key, status, priority in rows:
        repo.add(KeyedJob(id=label, seq=seq, key=key, status=status, priority=priority))


def _skip_unless_postgresql(test_domain) -> None:
    dao = test_domain.repository_for(KeyedJob)._dao
    if dao.provider._engine.dialect.name != "postgresql":
        pytest.skip("the single-statement claim is PostgreSQL only")


def _skip_if_postgresql(test_domain) -> None:
    dao = test_domain.repository_for(KeyedJob)._dao
    engine = getattr(getattr(dao, "provider", None), "_engine", None)
    if engine is not None and engine.dialect.name == "postgresql":
        pytest.skip("PostgreSQL claims in one statement, with no guarded update")


def _claim_keyed(test_domain, hold_back=HOLD_BY_KEY, limit=10):
    dao = test_domain.repository_for(KeyedJob)._dao
    claimed = dao._claim(
        Q(status="ready"),
        {"status": "claimed"},
        limit=limit,
        order_by=["-priority", "seq"],
        hold_back=hold_back,
    )
    return [job.id for job in claimed]


def _key_rows(key: str, seqs: range, prefix: str | None = None) -> list[tuple]:
    return [_row(f"{prefix or key}-{n}", n, key) for n in seqs]


# One case per cell of what the hold-back claim decides over: whether the
# candidate is grouped, how an earlier row relates to it (same key, another
# key, a key that differs only in case, another lane), that row's state
# (claimable now, unfinished outside the criteria, claimed by another call,
# finished), whether claim order and commit order agree, and how the limit
# compares with the group and with the default query limit of 100. Rows are
# ``(label, seq, key, status, priority)``, and the claim takes "ready" rows in
# ``-priority, seq`` order.
HOLD_BACK_CASES = [
    pytest.param(
        [_row("b", 1, "k1"), _row("a", 0, "k1", "failed")],
        None,
        10,
        ["b"],
        id="no-hold-back-an-unfinished-earlier-row-holds-nothing",
    ),
    pytest.param(
        [_row("a", 0, None, "failed"), _row("b", 1, None)],
        HOLD_BY_KEY,
        10,
        ["b"],
        id="ungrouped-an-unfinished-earlier-row-holds-nothing",
    ),
    pytest.param(
        [_row("a", 0, "k1")],
        HOLD_BY_KEY,
        10,
        ["a"],
        id="grouped-with-no-earlier-row",
    ),
    pytest.param(
        [_row("c", 2, "k1"), _row("b", 1, "k1"), _row("a", 0, "k1")],
        HOLD_BY_KEY,
        10,
        ["a", "b", "c"],
        id="earlier-claimable-rows-are-claimed-together",
    ),
    pytest.param(
        [_row("b", 1, "k1"), _row("a", 0, "k1", "failed")],
        HOLD_BY_KEY,
        10,
        [],
        id="earlier-row-outside-the-criteria-holds",
    ),
    pytest.param(
        [_row("a", 0, "k1", "claimed"), _row("b", 1, "k1")],
        HOLD_BY_KEY,
        10,
        [],
        id="earlier-row-claimed-by-another-call-holds",
    ),
    pytest.param(
        [_row("b", 1, "k1"), _row("a", 0, "k1", "done")],
        HOLD_BY_KEY,
        10,
        ["b"],
        id="earlier-finished-row-holds-nothing",
    ),
    pytest.param(
        [_row("a", 0, "k1"), _row("b", 1, "k1", "failed"), _row("c", 2, "k1")],
        HOLD_BY_KEY,
        10,
        ["a"],
        id="unfinished-row-in-the-middle-holds-the-rest",
    ),
    pytest.param(
        [_row("a", 0, "k1", priority=1), _row("b", 1, "k1", priority=2)],
        HOLD_BY_KEY,
        10,
        ["a"],
        id="earlier-row-with-lower-priority-goes-first",
    ),
    pytest.param(
        [_row("a", 0, "k1", priority=2), _row("b", 1, "k1", priority=1)],
        HOLD_BY_KEY,
        10,
        ["a", "b"],
        id="earlier-row-with-higher-priority-goes-first",
    ),
    pytest.param(
        [
            _row("k1-b", 1, "k1"),
            _row("k1-a", 0, "k1", "failed"),
            _row("k2-a", 2, "k2"),
            _row("none-a", 3, None),
        ],
        HOLD_BY_KEY,
        10,
        ["k2-a", "none-a"],
        id="other-keys-and-ungrouped-rows-keep-flowing",
    ),
    pytest.param(
        [_row("upper-a", 0, "ACME", "failed"), _row("lower-a", 1, "acme")],
        HOLD_BY_KEY,
        10,
        ["lower-a"],
        id="keys-that-differ-only-in-case-are-separate",
    ),
    pytest.param(
        [
            _row("low-a", 0, "k1", "failed"),
            _row("low-b", 1, "k1"),
            _row("high-b", 2, "k1", priority=10),
        ],
        HOLD_BY_KEY_AND_LANE,
        10,
        ["high-b"],
        id="rows-in-different-lanes-are-separate",
    ),
    pytest.param(
        [_row("high-a", 0, "k1", "failed", 10), _row("high-b", 1, "k1", priority=7)],
        HOLD_BY_KEY_AND_LANE,
        10,
        [],
        id="rows-in-the-same-lane-hold",
    ),
    pytest.param(
        [_row("a", 0, "k1"), _row("b", 1, "k1"), _row("c", 2, "k1")],
        HOLD_BY_KEY,
        2,
        ["a", "b"],
        id="limit-smaller-than-the-group",
    ),
    pytest.param(
        [
            _row("k1-0", 0, "k1", "failed"),
            *_key_rows("k1", range(1, 6)),
            *_key_rows("k2", range(10, 12)),
        ],
        HOLD_BY_KEY,
        2,
        ["k2-10", "k2-11"],
        id="held-backlog-past-the-limit-does-not-starve-other-keys",
    ),
    pytest.param(
        [_row("k1-0", 0, "k1", "failed"), *_key_rows("k1", range(1, 102))],
        HOLD_BY_KEY,
        101,
        [],
        id="page-past-the-default-query-limit-is-all-held",
    ),
    pytest.param(
        _key_rows("k1", range(120)),
        HOLD_BY_KEY,
        120,
        [f"k1-{n}" for n in range(120)],
        id="claims-past-the-default-query-limit-in-one-group",
    ),
]


@pytest.mark.transactional
class TestClaimHoldBack:
    """``_claim`` with ``hold_back`` on any transactional adapter."""

    @pytest.mark.parametrize(
        ("rows", "hold_back", "limit", "expected"), HOLD_BACK_CASES
    )
    def test_claim_decides_each_case(
        self, test_domain, rows, hold_back, limit, expected
    ):
        _keyed(test_domain, *rows)

        assert _claim_keyed(test_domain, hold_back=hold_back, limit=limit) == expected

    def test_a_row_claimed_by_an_earlier_call_holds_the_later_row(self, test_domain):
        _keyed(test_domain, _row("a", 0, "k1"))
        assert _claim_keyed(test_domain) == ["a"]
        _keyed(test_domain, _row("b", 1, "k1"))

        assert _claim_keyed(test_domain) == []

    def test_no_statement_binds_a_parameter_per_claimed_row(self, test_domain):
        # SQL Server allows 2,100 bound parameters in one statement, so a claim
        # that binds one per row fails on a large batch.
        dao = test_domain.repository_for(KeyedJob)._dao
        engine = getattr(getattr(dao, "provider", None), "_engine", None)
        if engine is None:
            pytest.skip("only a SQL adapter binds parameters")
        # SQLAlchemy is an optional extra, absent when only memory is tested.
        from sqlalchemy import event

        _keyed(test_domain, *_key_rows("k1", range(150)))
        _keyed(test_domain, *[_row(f"none-{n}", 200 + n, None) for n in range(150)])
        bound: list[int] = []

        def count_parameters(conn, cursor, statement, parameters, context, many):
            rows = parameters if many else [parameters]
            bound.extend(len(row) for row in rows)

        event.listen(engine, "before_cursor_execute", count_parameters)
        try:
            claimed = _claim_keyed(test_domain, limit=300)
        finally:
            event.remove(engine, "before_cursor_execute", count_parameters)

        assert len(claimed) == 300
        assert max(bound) < 50

    def test_a_lost_claim_on_an_earlier_row_holds_the_rest_of_its_key(
        self, test_domain, monkeypatch
    ):
        _skip_if_postgresql(test_domain)
        _keyed(test_domain, _row("a", 0, "k1"), _row("b", 1, "k1"), _row("c", 2, "k2"))
        dao = test_domain.repository_for(KeyedJob)._dao
        update_all = dao._update_all

        def another_worker_takes_a(criteria, values):
            # Another worker claims "a" between this call's read and its
            # guarded update, so the update matches no row.
            if "'a'" in str(criteria):
                return 0
            return update_all(criteria, values)

        monkeypatch.setattr(dao, "_update_all", another_worker_takes_a)

        claimed = dao._claim(
            Q(status="ready"),
            {"status": "claimed"},
            limit=10,
            order_by=["seq"],
            hold_back=HOLD_BY_KEY,
        )

        assert [job.id for job in claimed] == ["c"]

    def test_a_sql_page_leaves_out_the_rows_of_a_held_key(self, test_domain):
        dao = test_domain.repository_for(KeyedJob)._dao
        if not hasattr(dao, "provider") or not hasattr(dao.provider, "_engine"):
            pytest.skip("the page filter is in the SQLAlchemy adapter")
        _keyed(test_domain, _row("k1-0", 0, "k1", "failed"))
        _keyed(test_domain, *_key_rows("k1", range(1, 6)))
        _keyed(test_domain, _row("k2-0", 10, "k2"))

        page = dao._claim_candidates(Q(status="ready"), 3, 0, ["seq"], HOLD_BY_KEY)

        assert [job.id for job in page] == ["k2-0"]


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
        _keyed(test_domain, _row("a", 0, "k1"), _row("b", 1, "k1"))
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
                _row(f"{key}-{n}", n * len(keys) + i, key)
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
