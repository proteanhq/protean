"""Tests for Priority enum, processing_priority() context manager, and current_priority().

Covers enum semantics, context nesting, exception safety, thread isolation,
and asyncio task isolation.
"""

import asyncio
import threading

import pytest

from protean.utils.processing import Priority, current_priority, processing_priority


# ---------------------------------------------------------------------------
# Priority enum tests
# ---------------------------------------------------------------------------


def test_priority_enum_values():
    """Each Priority member has the correct integer value."""
    assert Priority.BULK == -100
    assert Priority.LOW == -50
    assert Priority.NORMAL == 0
    assert Priority.HIGH == 50
    assert Priority.CRITICAL == 100


def test_priority_enum_ordering():
    """Priority members are ordered BULK < LOW < NORMAL < HIGH < CRITICAL."""
    assert Priority.BULK < Priority.LOW
    assert Priority.LOW < Priority.NORMAL
    assert Priority.NORMAL < Priority.HIGH
    assert Priority.HIGH < Priority.CRITICAL


def test_priority_enum_is_int():
    """Priority members are true int instances (IntEnum)."""
    assert isinstance(Priority.HIGH, int)
    assert isinstance(Priority.BULK, int)
    assert isinstance(Priority.NORMAL, int)


# ---------------------------------------------------------------------------
# current_priority() default
# ---------------------------------------------------------------------------


def test_current_priority_default():
    """Returns Priority.NORMAL (0) when no context manager is active."""
    assert current_priority() == Priority.NORMAL
    assert current_priority() == 0


# ---------------------------------------------------------------------------
# processing_priority() context manager
# ---------------------------------------------------------------------------


def test_processing_priority_context_manager():
    """Sets priority within the block and restores it after exit."""
    assert current_priority() == Priority.NORMAL

    with processing_priority(Priority.HIGH):
        assert current_priority() == Priority.HIGH

    assert current_priority() == Priority.NORMAL


def test_processing_priority_nested_contexts():
    """Inner context overrides outer; both restore correctly on exit."""
    assert current_priority() == Priority.NORMAL

    with processing_priority(Priority.LOW):
        assert current_priority() == Priority.LOW

        with processing_priority(Priority.CRITICAL):
            assert current_priority() == Priority.CRITICAL

        # Inner exited -- back to LOW
        assert current_priority() == Priority.LOW

    # Outer exited -- back to NORMAL
    assert current_priority() == Priority.NORMAL


def test_processing_priority_with_raw_int():
    """Accepts a raw int instead of a Priority member."""
    with processing_priority(42):
        assert current_priority() == 42

    assert current_priority() == Priority.NORMAL


def test_processing_priority_restores_on_exception():
    """Priority is restored to its previous value even when an exception propagates."""
    assert current_priority() == Priority.NORMAL

    with pytest.raises(RuntimeError, match="boom"):
        with processing_priority(Priority.CRITICAL):
            assert current_priority() == Priority.CRITICAL
            raise RuntimeError("boom")

    assert current_priority() == Priority.NORMAL


# ---------------------------------------------------------------------------
# Thread isolation
# ---------------------------------------------------------------------------


def test_current_priority_thread_isolation():
    """Each thread has its own independent priority context."""
    barrier = threading.Barrier(2)
    results: dict[str, list[int]] = {"thread_a": [], "thread_b": []}

    def thread_a():
        with processing_priority(Priority.HIGH):
            results["thread_a"].append(current_priority())
            barrier.wait(timeout=5)  # sync so both threads read at the same time
            results["thread_a"].append(current_priority())

    def thread_b():
        with processing_priority(Priority.BULK):
            results["thread_b"].append(current_priority())
            barrier.wait(timeout=5)
            results["thread_b"].append(current_priority())

    t_a = threading.Thread(target=thread_a)
    t_b = threading.Thread(target=thread_b)
    t_a.start()
    t_b.start()
    t_a.join(timeout=10)
    t_b.join(timeout=10)

    # Each thread should see only its own priority, not the other's.
    assert results["thread_a"] == [Priority.HIGH, Priority.HIGH]
    assert results["thread_b"] == [Priority.BULK, Priority.BULK]


# ---------------------------------------------------------------------------
# asyncio isolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_current_priority_asyncio_isolation():
    """Two concurrent async tasks have independent priority contexts."""
    results: dict[str, list[int]] = {"task_a": [], "task_b": []}
    sync_event_a = asyncio.Event()
    sync_event_b = asyncio.Event()

    async def task_a():
        with processing_priority(Priority.HIGH):
            results["task_a"].append(current_priority())
            sync_event_a.set()  # signal task_b that task_a has set its priority
            await sync_event_b.wait()  # wait for task_b to set its priority
            results["task_a"].append(current_priority())

    async def task_b():
        with processing_priority(Priority.BULK):
            results["task_b"].append(current_priority())
            sync_event_b.set()
            await sync_event_a.wait()
            results["task_b"].append(current_priority())

    await asyncio.gather(task_a(), task_b())

    assert results["task_a"] == [Priority.HIGH, Priority.HIGH]
    assert results["task_b"] == [Priority.BULK, Priority.BULK]


@pytest.mark.asyncio
async def test_processing_priority_with_async_code():
    """Priority propagates through await chains within the same task."""

    async def inner_coroutine() -> int:
        # Simulate an async I/O operation
        await asyncio.sleep(0)
        return current_priority()

    async def middle_coroutine() -> int:
        return await inner_coroutine()

    # Without context -- default
    result = await middle_coroutine()
    assert result == Priority.NORMAL

    # With context -- priority propagates through the full await chain
    with processing_priority(Priority.CRITICAL):
        result = await middle_coroutine()
        assert result == Priority.CRITICAL

    # After context -- back to default
    result = await middle_coroutine()
    assert result == Priority.NORMAL


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_processing_priority_normal_is_noop():
    """Wrapping in processing_priority(NORMAL) is effectively a no-op."""
    assert current_priority() == Priority.NORMAL

    with processing_priority(Priority.NORMAL):
        assert current_priority() == Priority.NORMAL

    assert current_priority() == Priority.NORMAL


def test_processing_priority_zero_is_same_as_normal():
    """processing_priority(0) is equivalent to Priority.NORMAL."""
    with processing_priority(0):
        assert current_priority() == 0
        assert current_priority() == Priority.NORMAL

    assert current_priority() == Priority.NORMAL


def test_priority_members_cover_expected_names():
    """All expected priority level names exist on the enum."""
    expected = {"BULK", "LOW", "NORMAL", "HIGH", "CRITICAL"}
    actual = {member.name for member in Priority}
    assert actual == expected
