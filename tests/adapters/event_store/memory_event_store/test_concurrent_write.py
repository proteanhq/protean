"""Verify that the memory event store's version check + write is atomic
under concurrent access via threading.Lock."""

import threading


def test_concurrent_writes_with_expected_version(test_domain):
    """Two threads write to the same stream with the same expected_version.

    Exactly one must succeed; the other must raise ValueError because the
    version check and write are atomic under the lock.
    """
    stream = "testStream-concurrent"

    # Seed the stream so version is 0
    test_domain.event_store.store._write(stream, "Event1", {"seq": "seed"})

    barrier = threading.Barrier(2, timeout=5)
    results: dict[str, Exception | None] = {"t1": None, "t2": None}

    def write_with_version(key: str) -> None:
        ctx = test_domain.domain_context()
        ctx.push()
        try:
            barrier.wait()  # synchronize both threads
            test_domain.event_store.store._write(
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
    assert isinstance(errors[0], ValueError)
    assert "Wrong expected version" in str(errors[0])
