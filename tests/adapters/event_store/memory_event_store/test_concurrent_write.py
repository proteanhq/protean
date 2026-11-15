"""Verify that the memory event store's version check + write is atomic
under concurrent access via threading.Lock."""

import sys
import threading

import pytest

from protean.exceptions import ExpectedVersionError


def test_concurrent_writes_with_expected_version(test_domain):
    """Two threads write to the same stream with the same expected_version.

    Exactly one must succeed; the other must raise ExpectedVersionError because the
    version check and write are atomic under the lock.
    """
    stream = "testStream-concurrent"

    # Seed the stream so version is 0
    test_domain.event_store.store.write_message(stream, "Event1", {"seq": "seed"})

    barrier = threading.Barrier(2, timeout=5)
    results: dict[str, Exception | None] = {"t1": None, "t2": None}

    def write_with_version(key: str) -> None:
        ctx = test_domain.domain_context()
        ctx.push()
        try:
            barrier.wait()  # synchronize both threads
            test_domain.event_store.store.write_message(
                stream, "Event1", {"seq": key}, expected_version=0
            )
        except Exception as exc:
            results[key] = exc
        finally:
            ctx.pop()

    t1 = threading.Thread(target=write_with_version, args=("t1",))
    t2 = threading.Thread(target=write_with_version, args=("t2",))

    t1.start()
    t2.start()
    t1.join(timeout=10)
    t2.join(timeout=10)
    assert not t1.is_alive(), "Thread t1 did not complete within timeout"
    assert not t2.is_alive(), "Thread t2 did not complete within timeout"

    # Exactly one thread must have failed
    errors = [v for v in results.values() if v is not None]
    assert len(errors) == 1, (
        f"Expected exactly one failure, got {len(errors)}: {results}"
    )
    assert isinstance(errors[0], ExpectedVersionError)
    assert "Wrong expected version" in str(errors[0])


def test_write_with_wrong_expected_version_raises_expected_version_error(
    test_domain,
):
    stream = "testStream-wrong-version"
    test_domain.event_store.store.write_message(stream, "Event1", {"seq": "seed"})

    with pytest.raises(ExpectedVersionError) as exc_info:
        test_domain.event_store.store.write_message(
            stream, "Event1", {"seq": "stale"}, expected_version=5
        )

    assert str(exc_info.value) == (
        f"Wrong expected version: 5 (Stream: {stream}, Stream Version: 0)"
    )


def test_fifty_writers_get_one_success_per_expected_version(test_domain):
    """Fifty threads each read the stream version and write with it.

    Exactly one write per expected version succeeds, the stream's positions
    run 0..n-1 with no gaps, and the store's global positions run 1..n.
    """
    store = test_domain.event_store.store
    stream = "testStream-fifty"
    thread_count = 50
    attempts_per_thread = 20

    barrier = threading.Barrier(thread_count, timeout=10)
    lock = threading.Lock()
    successes: list[int] = []
    conflicts: list[ExpectedVersionError] = []
    unexpected: list[BaseException] = []

    def writer() -> None:
        ctx = test_domain.domain_context()
        ctx.push()
        try:
            barrier.wait()
            for _ in range(attempts_per_thread):
                last = store.get_last_stream_message(stream)
                version = last["position"] if last is not None else -1
                try:
                    store.write_message(
                        stream, "Event1", {"v": version}, expected_version=version
                    )
                except ExpectedVersionError as exc:
                    with lock:
                        conflicts.append(exc)
                else:
                    with lock:
                        successes.append(version)
        except BaseException as exc:  # surfaced by the assertion below
            with lock:
                unexpected.append(exc)
        finally:
            ctx.pop()

    # A short switch interval makes threads swap often, so writers interleave
    # between the version check and the append when the lock is missing.
    previous_interval = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)
    try:
        threads = [threading.Thread(target=writer) for _ in range(thread_count)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=60)
    finally:
        sys.setswitchinterval(previous_interval)

    assert not any(thread.is_alive() for thread in threads)
    assert unexpected == []
    assert conflicts, "the threads never contended for a version"

    n = len(successes)
    assert n > 0
    assert sorted(successes) == list(range(-1, n - 1))

    messages = store.get_stream_messages(stream, limit=n + 1)
    assert [m["position"] for m in messages] == list(range(n))
    all_messages = store.get_all_messages(limit=n + 1)
    assert [m["global_position"] for m in all_messages] == list(range(1, n + 1))
