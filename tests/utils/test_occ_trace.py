"""Unit tests for the OCC trace recorder (:issue:`#1382`).

The recorder in ``protean.utils.occ_trace`` is a diagnostic seam: inactive by
default (so the adapters pay nothing on the normal path), activated by a
process-wide :func:`~protean.utils.occ_trace.capture` context that concurrent
writer threads share. These tests pin that contract; the adapter emits are
exercised separately against the real Memory and SQLAlchemy commit paths.
"""

import threading

import pytest

from protean.utils import occ_trace

# Pure recorder unit tests: they never touch a domain, so skip the autouse
# ``test_domain`` fixture rather than building a Domain for each one.
pytestmark = pytest.mark.no_test_domain


def test_inactive_by_default():
    assert occ_trace.is_active() is False


def test_record_is_a_noop_when_inactive():
    # No capture in progress, so this must return quietly and record nothing.
    occ_trace.record(
        stream="s", writer="w", base=0, outcome="committed", version_after=1
    )
    assert occ_trace.is_active() is False


def test_capture_activates_collects_and_restores():
    assert occ_trace.is_active() is False
    with occ_trace.capture() as events:
        assert occ_trace.is_active() is True
        occ_trace.record(
            stream="counter:1",
            writer="w1",
            base=0,
            outcome="committed",
            version_after=1,
        )
        occ_trace.record(
            stream="counter:1",
            writer="w2",
            base=0,
            outcome="conflicted",
            version_after=1,
        )
    assert occ_trace.is_active() is False
    assert events == [
        {
            "stream": "counter:1",
            "writer": "w1",
            "base": 0,
            "outcome": "committed",
            "version_after": 1,
        },
        {
            "stream": "counter:1",
            "writer": "w2",
            "base": 0,
            "outcome": "conflicted",
            "version_after": 1,
        },
    ]


def test_record_defaults_writer_to_the_current_thread_id():
    # The adapters call record() without a writer; it fills in the thread id, which
    # uniquely tags each concurrent unit of work.
    with occ_trace.capture() as events:
        occ_trace.record(stream="s", base=0, outcome="committed", version_after=1)
    assert events[0]["writer"] == str(threading.get_ident())


def test_capture_restores_even_on_error():
    with pytest.raises(RuntimeError):
        with occ_trace.capture():
            assert occ_trace.is_active() is True
            raise RuntimeError("boom")
    # The finally in capture() must have restored the previous (inactive) state.
    assert occ_trace.is_active() is False


def test_nested_captures_do_not_leak():
    with occ_trace.capture() as outer:
        occ_trace.record(
            stream="s", writer="outer", base=0, outcome="committed", version_after=1
        )
        with occ_trace.capture() as inner:
            occ_trace.record(
                stream="s", writer="inner", base=1, outcome="committed", version_after=2
            )
        # The inner capture collected only its own event and restored the outer.
        assert [e["writer"] for e in inner] == ["inner"]
        assert occ_trace.is_active() is True
        occ_trace.record(
            stream="s", writer="outer2", base=0, outcome="conflicted", version_after=2
        )
    assert [e["writer"] for e in outer] == ["outer", "outer2"]
    assert occ_trace.is_active() is False


def test_record_is_thread_safe_under_contention():
    # Concurrent appends must not drop events: the recorder guards the shared log
    # with a lock precisely because the writer threads race.
    with occ_trace.capture() as events:

        def worker(n: int) -> None:
            occ_trace.record(
                stream="s",
                writer=str(n),
                base=0,
                outcome="conflicted",
                version_after=1,
            )

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(50)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)
        assert not any(thread.is_alive() for thread in threads), "a worker hung"
    assert len(events) == 50
    assert {e["writer"] for e in events} == {str(i) for i in range(50)}
