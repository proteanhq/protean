"""Unit tests for the checkpoint trace recorder (:issue:`#1384`).

The recorder in ``protean.utils.checkpoint_trace`` is a diagnostic seam: inactive by
default (so the subscription pays one boolean read per tick on the normal path),
activated by a process-wide :func:`~protean.utils.checkpoint_trace.capture` context.
These tests pin that contract; the subscription emits are exercised separately
against the real ``_gap_safe_batch`` path in ``tests/subscription``.
"""

import threading

import pytest

from protean.utils import checkpoint_trace

# Pure recorder unit tests: they never touch a domain, so skip the autouse
# ``test_domain`` fixture rather than building a Domain for each one.
pytestmark = pytest.mark.no_test_domain


def test_inactive_by_default():
    assert checkpoint_trace.is_active() is False


def test_record_is_a_noop_when_inactive():
    # No capture in progress, so this must return quietly and record nothing.
    checkpoint_trace.record(cursor=0, present=[1], abandoned=[], safe=1)
    assert checkpoint_trace.is_active() is False


def test_capture_activates_collects_and_restores():
    assert checkpoint_trace.is_active() is False
    with checkpoint_trace.capture() as events:
        assert checkpoint_trace.is_active() is True
        checkpoint_trace.record(cursor=0, present=[1, 3], abandoned=[], safe=1)
        checkpoint_trace.record(cursor=1, present=[3], abandoned=[2], safe=3)
    assert checkpoint_trace.is_active() is False
    assert events == [
        {"cursor": 0, "present": [1, 3], "abandoned": [], "safe": 1},
        {"cursor": 1, "present": [3], "abandoned": [2], "safe": 3},
    ]


def test_record_sorts_and_copies_position_lists():
    # The lists are sorted (so the recorded order is deterministic regardless of the
    # set-iteration order the caller passes) and copied (so a later mutation of the
    # caller's list cannot reach back into the recorded event).
    caller_present = [3, 1]
    caller_abandoned = [2]
    with checkpoint_trace.capture() as events:
        checkpoint_trace.record(
            cursor=0, present=caller_present, abandoned=caller_abandoned, safe=1
        )
        caller_present.append(99)
        caller_abandoned.append(88)
    assert events == [{"cursor": 0, "present": [1, 3], "abandoned": [2], "safe": 1}]


def test_capture_restores_even_on_error():
    with pytest.raises(RuntimeError):
        with checkpoint_trace.capture():
            assert checkpoint_trace.is_active() is True
            raise RuntimeError("boom")
    # The finally in capture() must have restored the previous (inactive) state.
    assert checkpoint_trace.is_active() is False


def test_nested_captures_do_not_leak():
    with checkpoint_trace.capture() as outer:
        checkpoint_trace.record(cursor=0, present=[1], abandoned=[], safe=1)
        with checkpoint_trace.capture() as inner:
            checkpoint_trace.record(cursor=1, present=[2], abandoned=[], safe=2)
        # The inner capture collected only its own event and restored the outer.
        assert inner == [{"cursor": 1, "present": [2], "abandoned": [], "safe": 2}]
        assert checkpoint_trace.is_active() is True
        checkpoint_trace.record(cursor=2, present=[3], abandoned=[], safe=3)
    assert [e["safe"] for e in outer] == [1, 3]
    assert checkpoint_trace.is_active() is False


def test_record_is_thread_safe_under_contention():
    # Concurrent appends must not drop events: the recorder guards the shared log
    # with a lock, mirroring occ_trace, so a future concurrent driver is safe.
    with checkpoint_trace.capture() as events:

        def worker(n: int) -> None:
            checkpoint_trace.record(cursor=n, present=[n], abandoned=[], safe=n)

        # Daemon so a hung worker cannot keep the pytest process alive and stall the
        # run; the assertion below still validates that they all finished.
        threads = [
            threading.Thread(target=worker, args=(i,), daemon=True) for i in range(50)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)
        assert not any(thread.is_alive() for thread in threads), "a worker hung"
    assert len(events) == 50
    assert {e["cursor"] for e in events} == set(range(50))
