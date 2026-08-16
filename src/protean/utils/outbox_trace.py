"""Record the transactional-outbox two-phase publish as the real code runs it.

``specs/Outbox.tla`` states what the claim/publish/mark protocol is *allowed* to do;
TLC never reads the Python, so nothing today confirms the shipped ``OutboxProcessor``
behaves the way the model says. This recorder closes that gap the other way round.
When a capture is in progress, the real outbox path emits the raw transitions the
spec talks about, in the order they happen:

- ``claim`` — a row was atomically claimed and marked PROCESSING under a lock (the
  production ``OutboxRepository.claim_batch`` path), held by the recorded worker.
- ``publish`` — the broker publish was attempted; ``outcome`` is ``"ok"`` when the
  broker received the message, ``"fail"`` when it did not.
- ``mark`` — the row's terminal status was set inside the commit; ``outcome`` is the
  resulting status (``"published"``, ``"failed"``, or ``"abandoned"``).
- ``crash`` — a worker dropped the message mid-flight without marking it. A crash is a
  process event, not a code branch, so it is recorded by the harness, not emitted from
  the processor.
- ``lock_expire`` — the claim lock on a crashed row lapsed, returning it to the
  claimable pool. Like ``crash`` this is a time/process event the harness records.

``specs/check.sh`` feeds that log to TLC and confirms it is a behaviour
``Outbox.tla`` permits (see ``specs/OutboxTrace.tla``), that it witnesses the
redelivery from a crash after the broker publish but before the mark (the window the
protocol exists for), and that a seeded mark-without-publish is rejected.

The recorder is inactive by default, so the outbox path pays nothing on the normal
path: :func:`record` returns on its first line unless a :func:`capture` is in
progress. This mirrors :mod:`protean.utils.occ_trace` and
:mod:`protean.utils.recovery_trace`; like those it is an internal diagnostic seam,
not part of the public surface.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Literal, TypedDict

Action = Literal["claim", "publish", "mark", "crash", "lock_expire"]


class OutboxEvent(TypedDict):
    """One observed transition of the outbox two-phase publish.

    ``action`` is the transition; ``worker`` and ``message`` are the raw identifiers
    the transition concerns (the converter maps each distinct value to a small
    integer, so their exact form does not matter here). ``outcome`` is meaningful for
    ``publish`` (``"ok"``/``"fail"``) and ``mark`` (the resulting status); it is
    ``None`` for ``claim``, ``crash``, and ``lock_expire``.
    """

    action: Action
    worker: str
    message: str
    outcome: str | None


# The active log, or None when no capture is in progress. Guarded by _lock so the
# pointer swap in capture() cannot race an append. The claim emit runs on a worker
# thread (claim_batch is dispatched via asyncio.to_thread), so, like occ_trace, the
# lock keeps concurrent appends safe rather than relying on single-threaded use.
_lock = threading.Lock()
_events: list[OutboxEvent] | None = None


def is_active() -> bool:
    """Whether a capture is in progress."""
    return _events is not None


def record(
    *,
    action: Action,
    worker: str,
    message: str,
    outcome: str | None = None,
) -> None:
    """Append one observed outbox transition to the active log.

    A no-op unless a :func:`capture` is in progress, so the outbox path can call it
    unconditionally. See :class:`OutboxEvent` for the fields.
    """
    if _events is None:
        return  # fast, lock-free path when inactive (the common case)
    with _lock:
        # Re-read under the lock so a nested capture() swap (also taken under the
        # lock) can never land this append on a list that has already been restored.
        events = _events
        if events is None:  # pragma: no cover — only reachable if record races a swap
            return
        events.append(
            OutboxEvent(action=action, worker=worker, message=message, outcome=outcome)
        )


@contextmanager
def capture() -> Iterator[list[OutboxEvent]]:
    """Activate the recorder for the duration of the block, yielding the shared log.

    Restores the previous recorder on exit, so captures nest and an error inside the
    block cannot leave the recorder wedged on. The pointer swap is taken under the
    same lock as the appends.
    """
    global _events
    fresh: list[OutboxEvent] = []
    with _lock:
        previous = _events
        _events = fresh
    try:
        yield fresh
    finally:
        with _lock:
            _events = previous
