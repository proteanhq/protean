"""Concurrent writers never silently lose an update, across a range of
concurrency levels (:issue:`#1251`).

For each worker count, N writers load one aggregate at the same version, all
commit after a barrier, and the no-lost-update invariant must hold: the number
of writers that reported success equals the aggregate's final ``_version`` (a
silent lost update would report more successes than versions), exactly one
writer wins the race for a given version, and the rest raise
``ExpectedVersionError``.

A threaded race is deliberately *not* driven by Hypothesis — it is
non-deterministic and side-effecting, so it does not shrink meaningfully;
``parametrize`` over concurrency level is the property here. Needs a real
PostgreSQL backend (the in-memory adapter's process lock masks the race), so it
runs only under the full adapter suite.
"""

import threading

import pytest

from protean import Domain
from protean.core.aggregate import BaseAggregate
from protean.core.unit_of_work import UnitOfWork
from protean.exceptions import ExpectedVersionError
from protean.fields import Integer, String
from tests.shared import POSTGRES_PORT

pytestmark = pytest.mark.no_test_domain

_MAX_WORKERS = 8
_WORKER_COUNTS = [2, 3, 5, 8]


class OCCCounter(BaseAggregate):
    label: String(max_length=20, required=False)
    value: Integer(default=0)


@pytest.fixture
def concurrency_domain():
    """A postgres domain with a connection pool sized for the widest race."""
    domain = Domain(
        name="Verification concurrency",
        config={
            "identity_type": "uuid",
            "databases": {
                "default": {
                    "provider": "postgresql",
                    "database_uri": (
                        f"postgresql://postgres:postgres@localhost:{POSTGRES_PORT}/postgres"
                    ),
                    "pool_size": _MAX_WORKERS + 4,
                    "max_overflow": 4,
                }
            },
        },
    )
    domain.register(OCCCounter)
    domain.init(traverse=False)

    provider = domain.providers["default"]
    domain.repository_for(OCCCounter)._dao  # materialize the model before create_all
    provider._metadata.create_all(provider._engine)
    try:
        with domain.domain_context():
            yield domain
    finally:
        provider._metadata.drop_all(provider._engine)
        provider.close()


@pytest.mark.postgresql
@pytest.mark.parametrize("workers", _WORKER_COUNTS)
def test_no_lost_update_at_any_concurrency(concurrency_domain, workers):
    domain = concurrency_domain

    with UnitOfWork():
        seed = OCCCounter(value=0)
        domain.repository_for(OCCCounter).add(seed)
    counter_id = seed.id

    # Every worker loads the same version before any commits, forcing a real race.
    load_barrier = threading.Barrier(workers, timeout=20)
    results: list[str] = []
    results_lock = threading.Lock()

    def worker(worker_no: int) -> None:
        try:
            with domain.domain_context(), UnitOfWork():
                repo = domain.repository_for(OCCCounter)
                counter = repo.get(counter_id)
                counter.value = worker_no + 1
                load_barrier.wait()
                repo.add(counter)
            outcome = "success"
        except ExpectedVersionError:
            outcome = "conflict"
        except Exception as exc:  # pragma: no cover — surfaced by the assertion below
            outcome = f"error:{type(exc).__name__}"
        with results_lock:
            results.append(outcome)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(workers)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    success = results.count("success")
    conflict = results.count("conflict")

    assert len(results) == workers, results
    assert all(o in ("success", "conflict") for o in results), results

    with UnitOfWork():
        final = domain.repository_for(OCCCounter).get(counter_id)

    # The invariant the bug violated: one success per version. A silent lost
    # update would report more successes than the final version advanced.
    assert success == final._version, (
        f"lost update at {workers} workers: {success} successes, "
        f"version {final._version}"
    )
    assert success == 1
    assert conflict == workers - 1
