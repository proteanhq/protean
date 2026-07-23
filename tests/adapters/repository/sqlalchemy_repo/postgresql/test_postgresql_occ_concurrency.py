"""Concurrency regression for optimistic-concurrency lost updates.

The bug: the aggregate version check was a non-atomic read-compare-write, so two
transactions could both read the same version and both write — silently losing an
update with no ``ExpectedVersionError``. The fix maps a SQLAlchemy
``version_id_col`` so the update flush is guarded by ``WHERE _version = :loaded``
and a stale write raises ``StaleDataError`` (surfaced as ``ExpectedVersionError``).

This needs a real PostgreSQL backend (the in-memory adapter uses a process-wide
lock that masks the race) and one live connection per worker thread, so the test
runs against its own domain with a pool sized for the concurrency rather than the
shared ``pool_size = 1`` fixture.
"""

import threading

import pytest
from sqlalchemy import text

from protean import Domain
from protean.core.aggregate import BaseAggregate
from protean.core.entity import BaseEntity
from protean.core.unit_of_work import UnitOfWork
from protean.exceptions import ExpectedVersionError
from protean.fields import HasMany, Integer, Reference, String
from tests.shared import POSTGRES_PORT

# This module builds its own Domain (``concurrency_domain``), so skip the autouse
# ``test_domain`` fixture per the repo convention.
pytestmark = pytest.mark.no_test_domain

_WORKERS = 8


class OCCCounter(BaseAggregate):
    label: String(max_length=20, required=False)
    value: Integer(default=0)


class OCCOrder(BaseAggregate):
    label: String(max_length=20, required=False)
    lines = HasMany("OCCLine")


class OCCLine(BaseEntity):
    sku: String(max_length=20, required=True)
    quantity: Integer(default=0)

    # Named to match the HasMany back-reference derived from ``OCCOrder``.
    occ_order = Reference(OCCOrder)


@pytest.fixture
def concurrency_domain():
    """A postgres domain with one connection per worker thread (plus headroom)."""
    domain = Domain(
        name="OCC concurrency",
        config={
            "identity_type": "uuid",
            "databases": {
                "default": {
                    "provider": "postgresql",
                    "database_uri": (
                        f"postgresql://postgres:postgres@localhost:{POSTGRES_PORT}/postgres"
                    ),
                    "pool_size": _WORKERS + 4,
                    "max_overflow": 4,
                }
            },
        },
    )
    domain.register(OCCCounter)
    domain.register(OCCOrder)
    domain.register(OCCLine, part_of=OCCOrder)
    domain.init(traverse=False)

    provider = domain.providers["default"]
    # Touch each DAO so the SQLAlchemy models + their tables are materialized
    # into the provider metadata before create_all.
    domain.repository_for(OCCCounter)._dao
    domain.repository_for(OCCOrder)._dao
    domain.repository_for(OCCLine)._dao
    provider._metadata.create_all(provider._engine)
    try:
        with domain.domain_context():
            yield domain
    finally:
        provider._metadata.drop_all(provider._engine)
        provider.close()


def _seed_occ_order(domain):
    """Persist an OCCOrder with a single line at version 0; return its id."""
    with UnitOfWork():
        seed = OCCOrder(label="seed")
        seed.add_lines(OCCLine(sku="A", quantity=0))
        domain.repository_for(OCCOrder).add(seed)
    return seed.id


@pytest.mark.postgresql
def test_concurrent_updates_do_not_silently_lose_writes(concurrency_domain):
    domain = concurrency_domain

    # Seed a single aggregate at version 0.
    with UnitOfWork():
        seed = OCCCounter(value=0)
        domain.repository_for(OCCCounter).add(seed)
    counter_id = seed.id

    # Every worker loads version 0 before any of them commits — this is what
    # makes the writes genuinely concurrent rather than sequential.
    load_barrier = threading.Barrier(_WORKERS, timeout=20)
    results: list[str] = []
    results_lock = threading.Lock()

    def worker(worker_no: int) -> None:
        outcome: str
        try:
            with domain.domain_context(), UnitOfWork():
                repo = domain.repository_for(OCCCounter)
                counter = repo.get(counter_id)
                counter.label = f"w{worker_no}"
                counter.value = worker_no + 1
                load_barrier.wait()
                repo.add(counter)
            outcome = "success"
        except ExpectedVersionError:
            outcome = "conflict"
        except Exception as exc:  # reported via the assertion below
            outcome = f"error:{type(exc).__name__}"
        with results_lock:
            results.append(outcome)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(_WORKERS)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    success = results.count("success")
    conflict = results.count("conflict")

    # Every worker reported an outcome (no thread was abandoned by the join
    # timeout), and none failed for an unexpected reason (deadlock, crash).
    assert len(results) == _WORKERS, results
    assert all(o in ("success", "conflict") for o in results), results
    # The barrier forced a real race, so at least one writer must have lost it.
    assert conflict >= 1, results

    with UnitOfWork():
        final = domain.repository_for(OCCCounter).get(counter_id)

    # The invariant that the bug violated: every reported success advanced the
    # version exactly once, so the number of successes equals the final stored
    # version. A silent lost update reports more successes than versions.
    assert success == final._version, (
        f"lost update: {success} successes but version is {final._version}"
    )
    # Under the atomic guard exactly one writer wins the race for version 0.
    assert success == 1
    assert conflict == _WORKERS - 1
    assert final.value in range(1, _WORKERS + 1)


@pytest.mark.postgresql
def test_flush_time_version_conflict_raises_expected_version_error(concurrency_domain):
    """A version bump committed out-of-band after the add but before the UoW
    commit makes the flush's version_id_col guard match zero rows; the resulting
    StaleDataError surfaces as ExpectedVersionError (a deterministic, single-
    threaded exercise of the flush-time guard and its translation)."""
    domain = concurrency_domain

    with UnitOfWork():
        seed = OCCCounter(value=0)
        domain.repository_for(OCCCounter).add(seed)
    counter_id = seed.id

    with pytest.raises(ExpectedVersionError):
        with UnitOfWork():
            repo = domain.repository_for(OCCCounter)
            counter = repo.get(counter_id)
            counter.value = 5
            repo.add(counter)

            # Advance the row's version through an independent connection, after
            # the in-UoW read+add but before the deferred flush at commit.
            provider = domain.providers["default"]
            with provider._engine.connect() as conn:
                conn.execute(
                    text(
                        "UPDATE occ_counter SET _version = _version + 1 WHERE id = :id"
                    ),
                    {"id": counter_id},
                )
                conn.commit()
            # Exiting the UoW commits -> flush -> StaleDataError -> translated.


@pytest.mark.postgresql
def test_concurrent_child_only_updates_do_not_silently_lose_writes(concurrency_domain):
    """The aggregate root is the concurrency boundary: when every worker changes
    only a *child* field (no root-field change, no event), the root's version
    must still guard the write. Without the child->root propagation the root is
    never re-saved, so all writers "win" and updates are silently lost."""
    domain = concurrency_domain

    order_id = _seed_occ_order(domain)

    # Every worker loads version 0 before any of them commits. Each worker
    # writes its own distinct child value (worker_no + 1) so the surviving value
    # identifies which writer actually won.
    load_barrier = threading.Barrier(_WORKERS, timeout=20)
    results: list[tuple[int, str]] = []
    results_lock = threading.Lock()

    def worker(worker_no: int) -> None:
        outcome: str
        try:
            with domain.domain_context(), UnitOfWork():
                repo = domain.repository_for(OCCOrder)
                order = repo.get(order_id)
                # Mutate ONLY the child line's field — the root is untouched.
                order.lines[0].quantity = worker_no + 1
                load_barrier.wait()
                repo.add(order)
            outcome = "success"
        except ExpectedVersionError:
            outcome = "conflict"
        except Exception as exc:  # reported via the assertion below
            outcome = f"error:{type(exc).__name__}"
        with results_lock:
            results.append((worker_no, outcome))

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(_WORKERS)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    winners = [w for w, o in results if o == "success"]
    conflict = sum(1 for _, o in results if o == "conflict")

    assert len(results) == _WORKERS, results
    assert all(o in ("success", "conflict") for _, o in results), results

    with UnitOfWork():
        final = domain.repository_for(OCCOrder).get(order_id)

    # The invariant the bug violated: a child-only change advances the root
    # version, so exactly one writer wins the race for version 0 and the rest
    # conflict. A silent lost update would report more successes than the final
    # version.
    assert len(winners) == final._version, (
        f"lost update: {len(winners)} successes but version is {final._version}"
    )
    assert len(winners) == 1
    assert conflict == _WORKERS - 1
    # The surviving child value belongs to the single winning writer — not just
    # any writer (which would also catch a version bumped without the write).
    assert final.lines[0].quantity == winners[0] + 1


@pytest.mark.postgresql
def test_child_only_flush_conflict_raises_expected_version_error(concurrency_domain):
    """Deterministic, single-threaded exercise of the child-only flush guard.

    A child-only change re-saves the root, and because the aggregate has child
    rows to order, the root UPDATE is forced out at ``repo.add`` time via
    ``_flush`` (not at UoW commit). A version bump committed out-of-band between
    the read and that flush makes the version_id_col predicate match zero rows;
    the resulting StaleDataError must surface as ExpectedVersionError from the
    forced flush, just as the commit path translates it."""
    domain = concurrency_domain

    order_id = _seed_occ_order(domain)

    with pytest.raises(ExpectedVersionError):
        with UnitOfWork():
            repo = domain.repository_for(OCCOrder)
            order = repo.get(order_id)
            order.lines[0].quantity = 5

            # Advance the root's version through an independent connection, after
            # the in-UoW read+mutation but before the forced flush at add time.
            provider = domain.providers["default"]
            with provider._engine.connect() as conn:
                conn.execute(
                    text("UPDATE occ_order SET _version = _version + 1 WHERE id = :id"),
                    {"id": order_id},
                )
                conn.commit()

            # The child-only add re-saves the root and flushes -> StaleDataError
            # -> translated to ExpectedVersionError.
            repo.add(order)

    # The conflicting UoW rolled back: the in-flight child edit (quantity=5) was
    # discarded and the row reflects only the out-of-band version bump (0 -> 1),
    # not a second bump from the failed add.
    with UnitOfWork():
        final = domain.repository_for(OCCOrder).get(order_id)
    assert final._version == 1
    assert final.lines[0].quantity == 0
