"""Concurrency regression for optimistic-concurrency lost updates.

The bug: the SQLAlchemy ``_update`` used a non-atomic read-compare-write, so
under ``READ COMMITTED`` two transactions could both read the same version and
both write — silently losing an update with no ``ExpectedVersionError``. The
fix makes the write a single conditional ``UPDATE … WHERE _version = :expected``.

This needs a real PostgreSQL backend (the in-memory adapter uses a process-wide
lock that masks the race) and one live connection per worker thread, so the test
runs against its own domain with a pool sized for the concurrency rather than the
shared ``pool_size = 1`` fixture.
"""

import threading

import pytest

from protean import Domain
from protean.core.aggregate import BaseAggregate
from protean.core.unit_of_work import UnitOfWork
from protean.exceptions import ExpectedVersionError
from protean.fields import Integer, String
from tests.shared import POSTGRES_PORT

_WORKERS = 8


class OCCCounter(BaseAggregate):
    label: String(max_length=20, required=False)
    value: Integer(default=0)


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
    domain.init(traverse=False)

    provider = domain.providers["default"]
    # Touch the DAO so the SQLAlchemy model + its table are materialized into
    # the provider metadata before create_all.
    domain.repository_for(OCCCounter)._dao
    provider._metadata.create_all(provider._engine)
    try:
        with domain.domain_context():
            yield domain
    finally:
        provider._metadata.drop_all(provider._engine)
        provider.close()


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
