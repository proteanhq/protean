"""Record the ``$all`` gap-safe checkpoint advance as the real subscription runs it.

``specs/Checkpoint.tla`` states what the settle-then-process low-watermark
(ADR-0025, the gap-skip fix) is *allowed* to do; TLC never reads the Python,
so nothing today confirms the shipped subscription behaves the way the model says.
This recorder closes that gap the other way round. When a capture is in progress,
:meth:`EventStoreSubscription._gap_safe_batch` emits, once per batch, the raw state
it observed as it walked the batch: the cursor it started from, the set of
``global_position`` values present in the batch, each position it abandoned as a
timed-out hole, and the settled watermark it advanced the cursor to.
``specs/check.sh`` feeds that log to TLC and confirms it is a behaviour
``Checkpoint.tla`` permits (see ``specs/CheckpointTrace.tla``).

The values are raw observations, not a derived verdict: the recorder records what
the code saw (present / abandoned / cursor / watermark), and ``Checkpoint.tla``
does all the judging. ``specs/checkpoint_trace.py`` expands each batch observation
into the atomic transitions the model replays (a ``commit`` per newly-visible
position, an ``abandon`` per hole, an ``advance`` per real cursor move).

The recorder is inactive by default, so the subscription pays one boolean read per
tick on the normal path: :func:`record` returns on its first line unless a
:func:`capture` is in progress. A capture is process-wide, and appends are guarded
by a lock, mirroring :mod:`protean.utils.occ_trace` so the two recorders behave
the same way (and so a future concurrent driver is safe).
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from typing import TypedDict


class CheckpointEvent(TypedDict):
    """One ``_gap_safe_batch`` call's raw observation of the gap-safe advance.

    ``cursor`` is the read watermark the batch started from; ``present`` is the
    sorted set of ``global_position`` values in the batch (all above the cursor);
    ``abandoned`` is the sorted set of holes this batch stepped over after their
    gap timer elapsed; ``safe`` is the settled watermark the cursor advances to.
    All positions are raw ``global_position`` values, never a derived verdict.
    """

    cursor: int
    present: list[int]
    abandoned: list[int]
    safe: int


# The active log, or None when no capture is in progress. Process-wide on purpose,
# and guarded by _lock, mirroring protean.utils.occ_trace: the checkpoint driver is
# single-threaded today, but keeping the same shape means the two recorders cannot
# drift, and a concurrent driver would already be safe.
_lock = threading.Lock()
_events: list[CheckpointEvent] | None = None


def is_active() -> bool:
    """Whether a capture is in progress. The subscription tests this before emitting."""
    return _events is not None


def record(
    *,
    cursor: int,
    present: list[int],
    abandoned: list[int],
    safe: int,
) -> None:
    """Append one batch's observed gap-safe advance to the active log.

    A no-op unless a :func:`capture` is in progress, so the subscription can call
    it unconditionally on the batch path. See :class:`CheckpointEvent` for the
    fields; the lists are copied so a later mutation of the caller's list cannot
    reach back into the recorded event.
    """
    if _events is None:
        return  # fast, lock-free path when inactive (the common case)
    with _lock:
        # Re-read under the lock so a concurrent or nested capture() swap (also
        # taken under the lock) can never land this append on a list that has
        # already been restored. The None case here is only reachable if record()
        # races a capture() exit, which the single-driver usage never does.
        events = _events
        if events is None:  # pragma: no cover
            return
        events.append(
            CheckpointEvent(
                cursor=cursor,
                present=sorted(present),
                abandoned=sorted(abandoned),
                safe=safe,
            )
        )


@contextmanager
def capture() -> Iterator[list[CheckpointEvent]]:
    """Activate the recorder for the duration of the block, yielding the shared log.

    Restores the previous recorder on exit, so captures nest and an error inside
    the block cannot leave the recorder wedged on. The pointer swap is taken under
    the same lock as the appends, so a nested or concurrent capture cannot clobber
    it.
    """
    global _events
    fresh: list[CheckpointEvent] = []
    with _lock:
        previous = _events
        _events = fresh
    try:
        yield fresh
    finally:
        with _lock:
            _events = previous
