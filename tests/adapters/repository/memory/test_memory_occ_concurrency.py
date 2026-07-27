"""Concurrency regression for the in-memory adapter's optimistic locking.

The bug (#1258): a ``MemorySession`` deep-copied the whole store and committed
by replacing it wholesale. Two overlapping writers each passed the version
check against their own private copy and the last commit clobbered the rest,
with no ``ExpectedVersionError`` raised — a silent lost update.

The fix makes ``MemorySession.commit`` a real compare-and-set: it re-validates
each aggregate's version against the *live* store under the provider lock and
merges only its own changed records, key-by-key. So exactly one concurrent
writer of an aggregate wins and the rest raise ``ExpectedVersionError``, and
writers touching *different* records never clobber each other.

These tests contrast with ``test_postgresql_occ_concurrency.py``: that suite
proves the same property on a real relational backend; before this fix the
in-memory adapter could not stand in for it.
"""

import threading

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.entity import BaseEntity
from protean.core.unit_of_work import UnitOfWork
from protean.exceptions import ExpectedVersionError
from protean.fields import HasMany, Integer, Reference, String

_WORKERS = 8


class Counter(BaseAggregate):
    label: String(max_length=20, required=False)
    value: Integer(default=0)


class Order(BaseAggregate):
    label: String(max_length=20, required=False)
    lines = HasMany("OrderLine")


class OrderLine(BaseEntity):
    sku: String(max_length=20, required=True)
    quantity: Integer(default=0)

    order = Reference(Order)


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Counter)
    test_domain.register(Order)
    test_domain.register(OrderLine, part_of=Order)
    test_domain.init(traverse=False)


def _seed_counter(test_domain):
    with UnitOfWork():
        seed = Counter(value=0)
        test_domain.repository_for(Counter).add(seed)
    return seed.id


def _seed_order(test_domain):
    with UnitOfWork():
        seed = Order(label="seed")
        seed.add_lines(OrderLine(sku="A", quantity=0))
        test_domain.repository_for(Order).add(seed)
    return seed.id


def _run_workers(worker):
    threads = [
        threading.Thread(target=worker, args=(i,), daemon=True) for i in range(_WORKERS)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    # A thread still alive means it hung past the join timeout; fail loudly here
    # rather than letting a live thread mutate shared state under later asserts.
    assert not any(thread.is_alive() for thread in threads), (
        "a worker thread did not finish within the join timeout"
    )


def test_concurrent_updates_do_not_silently_lose_writes(test_domain):
    """Every worker loads version 0 before any commits, so the writes race.
    Exactly one wins; the rest raise ExpectedVersionError. Before the fix all
    eight "succeeded" and the version advanced once — seven lost updates."""
    counter_id = _seed_counter(test_domain)

    load_barrier = threading.Barrier(_WORKERS, timeout=20)
    results: list[tuple[int, str]] = []
    results_lock = threading.Lock()

    def worker(worker_no: int) -> None:
        try:
            with test_domain.domain_context(), UnitOfWork():
                repo = test_domain.repository_for(Counter)
                counter = repo.get(counter_id)
                counter.label = f"w{worker_no}"
                counter.value = worker_no + 1
                load_barrier.wait()
                repo.add(counter)
            outcome = "success"
        except ExpectedVersionError:
            outcome = "conflict"
        except Exception as exc:  # surfaced via the assertion below
            outcome = f"error:{type(exc).__name__}:{exc}"
        with results_lock:
            results.append((worker_no, outcome))

    _run_workers(worker)

    winners = [w for w, o in results if o == "success"]
    conflict = sum(1 for _, o in results if o == "conflict")

    assert len(results) == _WORKERS, results
    assert all(o in ("success", "conflict") for _, o in results), results

    with UnitOfWork():
        final = test_domain.repository_for(Counter).get(counter_id)

    # The invariant the bug violated: each success advances the version once, so
    # successes == final version. A silent lost update reports more successes.
    assert len(winners) == final._version, (
        f"lost update: {len(winners)} successes but version is {final._version}"
    )
    assert len(winners) == 1, results
    assert conflict == _WORKERS - 1, results
    # The surviving value belongs to the single winning writer — not just "some
    # writer's value", which a version bumped without the write would also pass.
    assert final.value == winners[0] + 1, (winners, final.value)


def test_concurrent_child_only_updates_do_not_silently_lose_writes(test_domain):
    """The aggregate root is the concurrency boundary: when every worker changes
    only a *child* line, the root's version must still guard the write."""
    order_id = _seed_order(test_domain)

    load_barrier = threading.Barrier(_WORKERS, timeout=20)
    results: list[tuple[int, str]] = []
    results_lock = threading.Lock()

    def worker(worker_no: int) -> None:
        try:
            with test_domain.domain_context(), UnitOfWork():
                repo = test_domain.repository_for(Order)
                order = repo.get(order_id)
                order.lines[0].quantity = worker_no + 1
                load_barrier.wait()
                repo.add(order)
            outcome = "success"
        except ExpectedVersionError:
            outcome = "conflict"
        except Exception as exc:  # surfaced via the assertion below
            outcome = f"error:{type(exc).__name__}:{exc}"
        with results_lock:
            results.append((worker_no, outcome))

    _run_workers(worker)

    winners = [w for w, o in results if o == "success"]
    conflict = sum(1 for _, o in results if o == "conflict")

    assert len(results) == _WORKERS, results
    assert all(o in ("success", "conflict") for _, o in results), results

    with UnitOfWork():
        final = test_domain.repository_for(Order).get(order_id)

    assert len(winners) == final._version, (
        f"lost update: {len(winners)} successes but version is {final._version}"
    )
    assert len(winners) == 1, results
    assert conflict == _WORKERS - 1, results
    # The surviving child value belongs to the single winning writer.
    assert final.lines[0].quantity == winners[0] + 1


def test_concurrent_updates_to_distinct_aggregates_all_succeed(test_domain):
    """Writers touching *different* aggregates must not conflict or clobber each
    other. Under the old wholesale-replace commit, one committer's snapshot
    overwrote the whole store and silently dropped the others' rows."""
    ids = [_seed_counter(test_domain) for _ in range(_WORKERS)]

    load_barrier = threading.Barrier(_WORKERS, timeout=20)
    results: list[str] = []
    results_lock = threading.Lock()

    def worker(worker_no: int) -> None:
        try:
            with test_domain.domain_context(), UnitOfWork():
                repo = test_domain.repository_for(Counter)
                counter = repo.get(ids[worker_no])
                counter.value = worker_no + 100
                load_barrier.wait()
                repo.add(counter)
            outcome = "success"
        except Exception as exc:  # surfaced via the assertion below
            outcome = f"error:{type(exc).__name__}:{exc}"
        with results_lock:
            results.append(outcome)

    _run_workers(worker)

    assert results == ["success"] * _WORKERS, results

    # Every distinct aggregate advanced to version 1 and kept its own value —
    # nothing was clobbered by a concurrent committer.
    with UnitOfWork():
        repo = test_domain.repository_for(Counter)
        for worker_no, identifier in enumerate(ids):
            final = repo.get(identifier)
            assert final._version == 1, (worker_no, final._version)
            assert final.value == worker_no + 100, (worker_no, final.value)


def test_commit_time_version_conflict_raises_expected_version_error(test_domain):
    """Deterministic exercise of the commit-time version check.

    A version bump applied to the *live* store after the in-UoW read+add but
    before the UoW commit makes the compare-and-set find a version it did not
    expect, so the commit raises ExpectedVersionError."""
    counter_id = _seed_counter(test_domain)
    provider = test_domain.providers["default"]

    with pytest.raises(ExpectedVersionError):
        with UnitOfWork():
            repo = test_domain.repository_for(Counter)
            counter = repo.get(counter_id)
            counter.value = 5
            repo.add(counter)

            # Advance the live row's version out-of-band (the memory analog of a
            # commit from an independent connection). The UoW's snapshot still
            # shows the old version, so only the commit-time check catches it.
            provider._databases["counter"][counter_id]["_version"] += 1
            # Exiting the UoW commits -> compare-and-set fails -> raises.

    # The conflicting UoW did not publish its change: value stays 0, and the
    # only version change is the out-of-band bump (0 -> 1).
    with UnitOfWork():
        final = test_domain.repository_for(Counter).get(counter_id)
    assert final._version == 1
    assert final.value == 0


def test_commit_time_vanished_record_raises_expected_version_error(test_domain):
    """A record deleted from the live store between the in-UoW read+add and the
    UoW commit makes the version check find nothing where it expected a version,
    which is a concurrency conflict -> ExpectedVersionError."""
    counter_id = _seed_counter(test_domain)
    provider = test_domain.providers["default"]

    with pytest.raises(ExpectedVersionError):
        with UnitOfWork():
            repo = test_domain.repository_for(Counter)
            counter = repo.get(counter_id)
            counter.value = 5
            repo.add(counter)

            # Delete the live row out-of-band before the commit.
            del provider._databases["counter"][counter_id]

    # The row stays gone; the failed commit did not resurrect it.
    assert counter_id not in provider._databases["counter"]


def test_create_then_update_same_aggregate_in_one_uow_commits_cleanly(test_domain):
    """A record created and then updated in the SAME UnitOfWork must commit
    cleanly. The commit-time version check must not treat the not-yet-published
    record as a concurrent conflict: it was created in this session, so it has
    no prior live version and the ``None`` there is expected, not a conflict."""
    with UnitOfWork():
        repo = test_domain.repository_for(Counter)
        counter = Counter(value=1)
        repo.add(counter)  # create
        counter.value = 2
        repo.add(counter)  # update the same aggregate, still in this UoW
    counter_id = counter.id

    # Committed without a spurious ExpectedVersionError, and the update stuck.
    persisted = test_domain.repository_for(Counter).get(counter_id)
    assert persisted.value == 2
