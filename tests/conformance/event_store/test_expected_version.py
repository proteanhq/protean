"""A write with a stale expected version raises and writes nothing.

The concurrent tests write from threads. Each write on an adapter with a
connection pool, such as Message DB, takes its own pooled connection, so the
writers race on separate connections.
"""

import sys
import threading

import pytest

from protean.exceptions import ExpectedVersionError
from protean.port.event_store import EventStoreCapabilities

pytestmark = pytest.mark.requires(
    EventStoreCapabilities.EXPECTED_VERSION, EventStoreCapabilities.READ_STREAM
)


def _write(adapter, stream_name: str, n: int, expected_version=None) -> int:
    return adapter.write_message(
        stream_name, "Counted", {"n": n}, expected_version=expected_version
    )


def _numbers(adapter, stream_name: str) -> list[int]:
    return [row["data"]["n"] for row in adapter.get_stream_messages(stream_name)]


def test_the_current_version_writes_at_the_next_position(adapter):
    _write(adapter, "user-1", 0)

    assert _write(adapter, "user-1", 1, expected_version=0) == 1
    assert _numbers(adapter, "user-1") == [0, 1]


def test_version_minus_one_writes_the_first_row_of_a_new_stream(adapter):
    assert _write(adapter, "user-1", 0, expected_version=-1) == 0


def test_version_minus_one_on_a_stream_with_rows_raises_and_writes_nothing(adapter):
    _write(adapter, "user-1", 0)

    with pytest.raises(ExpectedVersionError):
        _write(adapter, "user-1", 1, expected_version=-1)

    assert _numbers(adapter, "user-1") == [0]


@pytest.mark.parametrize("stale", [0, 5], ids=["behind", "ahead"])
def test_a_stale_version_raises_and_writes_nothing(adapter, stale):
    _write(adapter, "user-1", 0)
    _write(adapter, "user-1", 1)

    with pytest.raises(ExpectedVersionError):
        _write(adapter, "user-1", 2, expected_version=stale)

    assert _numbers(adapter, "user-1") == [0, 1]
    assert _write(adapter, "user-1", 3, expected_version=1) == 2


def test_a_stale_version_on_one_stream_leaves_other_streams_writable(adapter):
    _write(adapter, "user-1", 0)

    with pytest.raises(ExpectedVersionError):
        _write(adapter, "user-1", 1, expected_version=3)

    assert _write(adapter, "user-2", 2, expected_version=-1) == 0


def test_two_writers_with_the_same_version_commit_exactly_one_row(adapter, test_domain):
    _write(adapter, "user-1", 0)

    barrier = threading.Barrier(2, timeout=10)
    errors: dict[int, BaseException] = {}
    positions: dict[int, int] = {}

    def writer(n: int) -> None:
        with test_domain.domain_context():
            try:
                barrier.wait()
                positions[n] = _write(adapter, "user-1", n, expected_version=0)
            except BaseException as exc:  # checked below
                errors[n] = exc

    threads = [threading.Thread(target=writer, args=(n,)) for n in (1, 2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert not any(thread.is_alive() for thread in threads)
    assert list(positions.values()) == [1]
    assert len(errors) == 1
    assert isinstance(next(iter(errors.values())), ExpectedVersionError)
    winner = next(iter(positions))
    assert _numbers(adapter, "user-1") == [0, winner]


class _Outcome:
    """The results of the fifty writers, shared across their threads."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.successes: list[int] = []
        self.conflicts: list[ExpectedVersionError] = []
        self.unexpected: list[BaseException] = []


def _write_at_the_last_version(
    adapter, stream: str, outcome: _Outcome, barrier: threading.Barrier
) -> None:
    last = adapter.get_last_stream_message(stream)
    version = last["position"] if last is not None else -1
    # Every thread reads before any thread writes, so all fifty write with
    # the same version. Without the barrier, a fast runner can finish each
    # read and write before switching threads, and no write ever conflicts.
    barrier.wait()
    try:
        _write(adapter, stream, version, expected_version=version)
    except ExpectedVersionError as exc:
        with outcome.lock:
            outcome.conflicts.append(exc)
    else:
        with outcome.lock:
            outcome.successes.append(version)


def test_fifty_writers_get_one_success_per_expected_version(adapter, test_domain):
    """Fifty threads each read the stream's version and write with it.

    In each round all fifty threads write with the same version. Exactly one
    write per round succeeds, and the stream's positions run from 0 with no
    gaps.
    """
    stream = "user-1"
    thread_count = 50
    attempts_per_thread = 20

    barrier = threading.Barrier(thread_count, timeout=30)
    outcome = _Outcome()

    def writer() -> None:
        with test_domain.domain_context():
            try:
                for _ in range(attempts_per_thread):
                    _write_at_the_last_version(adapter, stream, outcome, barrier)
            except BaseException as exc:  # checked below
                with outcome.lock:
                    outcome.unexpected.append(exc)

    # Make the connection, or the pool, before the threads start, so they do
    # not race to create it.
    adapter.get_connection()

    # A short switch interval makes threads swap often, so writers interleave
    # between the version check and the append when the adapter has no lock.
    previous_interval = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)
    try:
        threads = [threading.Thread(target=writer) for _ in range(thread_count)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=120)
    finally:
        sys.setswitchinterval(previous_interval)

    assert not any(thread.is_alive() for thread in threads)
    assert outcome.unexpected == []
    n = attempts_per_thread
    assert len(outcome.conflicts) == n * (thread_count - 1)
    assert sorted(outcome.successes) == list(range(-1, n - 1))

    rows = adapter.get_stream_messages(stream, limit=n + 1)
    assert [row["position"] for row in rows] == list(range(n))
    assert [row["data"]["n"] for row in rows] == list(range(-1, n - 1))
    global_positions = [row["global_position"] for row in rows]
    assert global_positions == sorted(set(global_positions))
