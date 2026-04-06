"""Generic optimistic locking tests that run against all database providers.

Covers version increment on save, concurrent update detection, version
preservation through persist/retrieve round-trips, and true multi-threaded
race condition detection.
"""

import threading
from uuid import uuid4

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.unit_of_work import UnitOfWork
from protean.exceptions import ExpectedVersionError
from protean.fields import Integer, String


class Counter(BaseAggregate):
    name: String(max_length=100, required=True)
    value: Integer(default=0)


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Counter)
    test_domain.init(traverse=False)


@pytest.mark.basic_storage
class TestVersionIncrement:
    """Verify _version increments on each save."""

    def test_initial_version_is_minus_one(self, test_domain):
        counter = Counter(name="test", value=0)
        assert counter._version == -1

    def test_version_is_zero_after_first_persist(self, test_domain):
        counter = Counter(name="test", value=0)

        with UnitOfWork():
            test_domain.repository_for(Counter).add(counter)

        retrieved = test_domain.repository_for(Counter).get(counter.id)
        assert retrieved._version == 0

    def test_version_increments_on_update(self, test_domain):
        identifier = str(uuid4())
        counter = Counter(id=identifier, name="test", value=0)

        with UnitOfWork():
            test_domain.repository_for(Counter).add(counter)

        # First update
        retrieved = test_domain.repository_for(Counter).get(identifier)
        retrieved.value = 1
        with UnitOfWork():
            test_domain.repository_for(Counter).add(retrieved)

        after_first = test_domain.repository_for(Counter).get(identifier)
        assert after_first._version == 1

        # Second update
        after_first.value = 2
        with UnitOfWork():
            test_domain.repository_for(Counter).add(after_first)

        after_second = test_domain.repository_for(Counter).get(identifier)
        assert after_second._version == 2


@pytest.mark.basic_storage
class TestConcurrentUpdateDetection:
    """Verify stale writes are rejected with ExpectedVersionError."""

    def test_stale_write_raises_expected_version_error(self, test_domain):
        identifier = str(uuid4())
        counter = Counter(id=identifier, name="race", value=0)

        with UnitOfWork():
            test_domain.repository_for(Counter).add(counter)

        # Load two copies of the same aggregate
        copy1 = test_domain.repository_for(Counter).get(identifier)
        copy2 = test_domain.repository_for(Counter).get(identifier)

        # First copy succeeds
        copy1.value = 10
        with UnitOfWork():
            test_domain.repository_for(Counter).add(copy1)

        # Second copy (stale) should fail
        copy2.value = 20
        with pytest.raises(ExpectedVersionError):
            with UnitOfWork():
                test_domain.repository_for(Counter).add(copy2)

    def test_value_unchanged_after_concurrent_conflict(self, test_domain):
        identifier = str(uuid4())
        counter = Counter(id=identifier, name="conflict", value=0)

        with UnitOfWork():
            test_domain.repository_for(Counter).add(counter)

        copy1 = test_domain.repository_for(Counter).get(identifier)
        copy2 = test_domain.repository_for(Counter).get(identifier)

        # First copy wins
        copy1.value = 42
        with UnitOfWork():
            test_domain.repository_for(Counter).add(copy1)

        # Second copy fails
        copy2.value = 99
        with pytest.raises(ExpectedVersionError):
            with UnitOfWork():
                test_domain.repository_for(Counter).add(copy2)

        # Verify the winning value persisted
        final = test_domain.repository_for(Counter).get(identifier)
        assert final.value == 42


@pytest.mark.basic_storage
class TestVersionRoundTrip:
    """Verify _version survives persist/retrieve cycles."""

    def test_version_matches_after_initial_persist(self, test_domain):
        counter = Counter(name="roundtrip", value=0)

        with UnitOfWork():
            test_domain.repository_for(Counter).add(counter)

        retrieved = test_domain.repository_for(Counter).get(counter.id)
        assert retrieved._version == 0

    def test_version_matches_after_update(self, test_domain):
        identifier = str(uuid4())
        counter = Counter(id=identifier, name="roundtrip", value=0)

        with UnitOfWork():
            test_domain.repository_for(Counter).add(counter)

        # Update and verify version round-trips
        retrieved = test_domain.repository_for(Counter).get(identifier)
        assert retrieved._version == 0

        retrieved.value = 5
        with UnitOfWork():
            test_domain.repository_for(Counter).add(retrieved)

        updated = test_domain.repository_for(Counter).get(identifier)
        assert updated._version == 1
        assert updated.value == 5


@pytest.mark.basic_storage
class TestThreadedConcurrentUpdate:
    """Verify that truly concurrent (multi-threaded) writes are safe.

    Two threads modify the same aggregate simultaneously; exactly one must
    get ExpectedVersionError.
    """

    def test_concurrent_threads_one_wins_one_fails(self, test_domain):
        identifier = str(uuid4())
        counter = Counter(id=identifier, name="threaded-race", value=0)

        with UnitOfWork():
            test_domain.repository_for(Counter).add(counter)

        # Both threads load the same version
        copy1 = test_domain.repository_for(Counter).get(identifier)
        copy2 = test_domain.repository_for(Counter).get(identifier)

        barrier = threading.Barrier(2, timeout=5)
        results: dict[str, Exception | None] = {"t1": None, "t2": None}

        def update(copy, value, key):
            # Each thread needs its own domain context
            ctx = test_domain.domain_context()
            ctx.push()
            try:
                copy.value = value
                barrier.wait()  # Synchronize so both threads write at the same time
                with UnitOfWork():
                    test_domain.repository_for(Counter).add(copy)
            except Exception as exc:
                results[key] = exc
            finally:
                ctx.pop()

        t1 = threading.Thread(target=update, args=(copy1, 10, "t1"))
        t2 = threading.Thread(target=update, args=(copy2, 20, "t2"))

        t1.start()
        t2.start()
        t1.join(timeout=10)
        t2.join(timeout=10)
        assert not t1.is_alive(), "Thread t1 did not complete within timeout"
        assert not t2.is_alive(), "Thread t2 did not complete within timeout"

        # Exactly one thread must have failed with ExpectedVersionError
        errors = [v for v in results.values() if v is not None]
        assert len(errors) == 1, (
            f"Expected exactly one failure, got {len(errors)}: {results}"
        )
        assert isinstance(errors[0], ExpectedVersionError)

        # The winning value persisted, version advanced to 1
        final = test_domain.repository_for(Counter).get(identifier)
        assert final._version == 1
        assert final.value in (10, 20)
