"""Record the aggregate optimistic-concurrency (OCC) protocol as the real code runs it.

``specs/OCC.tla`` states what the OCC compare-and-set is *allowed* to do; TLC never
reads the Python, so nothing today confirms the shipped adapters behave the way the
model says. This recorder closes that gap the other way round. When a capture is in
progress, the real commit paths in the Memory and SQLAlchemy adapters emit, per unit
of work, the state each writer observed at its compare-and-set: the version it read
as its base, whether the commit went through or conflicted, and the resulting stored
version. ``specs/check.sh`` feeds that log to TLC and confirms it is a behaviour
``OCC.tla`` permits (see ``specs/OCCTrace.tla``).

The values are captured under the same lock or transaction as the real operation.
Almost all are read straight from the store rather than derived, so the log cannot
share a blind spot with the spec: the Memory path reads the stored version back after
its merge, and both adapters read the live version for a conflict. The one exception
is the SQLAlchemy *committed* ``version_after``, which is recorded as ``base + 1`` —
the value the ``version_id_col`` guard is guaranteed to set on a successful update,
since the standalone commit closes the connection before the row can be read back.

The recorder is inactive by default, so the adapters pay nothing on the normal path:
:func:`record` returns on its first line unless a :func:`capture` is in progress. A
capture is process-wide on purpose: concurrent writer threads emit into one shared
log, because their interleaving is exactly what the check validates. Appends are
guarded by a lock, since the writers race.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from threading import get_ident
from typing import Literal, TypedDict

Outcome = Literal["committed", "conflicted"]


class OCCEvent(TypedDict):
    """One unit of work's observed compare-and-set against a single version cell.

    ``stream`` groups events that contend for the same aggregate (one trace per
    stream). ``writer`` identifies the unit of work (a thread id, diagnostic
    only). ``base`` is the version this writer read as its expected base;
    ``outcome`` is the verdict; ``version_after`` is the resulting stored version
    (``base + 1`` on a commit), or ``None`` when a conflict left no readable row.
    """

    stream: str
    writer: str
    base: int
    outcome: Outcome
    version_after: int | None


# The active log, or None when no capture is in progress. Process-wide on purpose:
# concurrent writer threads append to one shared log so their interleaving is what the
# check sees. Guarded by _lock, which both the racing writers and capture() contend for.
_lock = threading.Lock()
_events: list[OCCEvent] | None = None


def is_active() -> bool:
    """Whether a capture is in progress. The adapters test this before doing any work."""
    return _events is not None


def record(
    *,
    stream: str,
    base: int,
    outcome: Outcome,
    version_after: int | None,
    writer: str | None = None,
) -> None:
    """Append one unit of work's observed compare-and-set to the active log.

    A no-op unless a :func:`capture` is in progress, so the adapters can call it
    unconditionally on the commit path. ``writer`` defaults to the current thread
    id, which uniquely tags each concurrent unit of work. See :class:`OCCEvent`
    for the fields.
    """
    events = _events
    if events is None:
        return
    with _lock:
        events.append(
            OCCEvent(
                stream=stream,
                writer=writer if writer is not None else str(get_ident()),
                base=base,
                outcome=outcome,
                version_after=version_after,
            )
        )


@contextmanager
def capture() -> Iterator[list[OCCEvent]]:
    """Activate the recorder for the duration of the block, yielding the shared log.

    Restores the previous recorder on exit, so captures nest and an error inside the
    block cannot leave the recorder wedged on. All writer threads spawned inside the
    block append to the one list this yields. The pointer swap is taken under the
    same lock as the appends, so a nested or concurrent capture cannot clobber it.
    """
    global _events
    fresh: list[OCCEvent] = []
    with _lock:
        previous = _events
        _events = fresh
    try:
        yield fresh
    finally:
        with _lock:
            _events = previous
