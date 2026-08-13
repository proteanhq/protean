"""Record the subscription failure-recovery protocol as the real code runs it.

``specs/Recovery.tla`` states what the record-before-advance protocol is *allowed*
to do; TLC never reads the Python, so nothing today confirms the shipped
``EventStoreSubscription`` behaves the way the model says. This recorder closes that
gap the other way round. When a capture is in progress, the real recovery path emits
the raw transitions the spec talks about, in the order they happen:

- ``handle_ok`` — the cursor advanced past a message that did not fail (a successful
  handle, or a skipped sync/idempotent message).
- ``fail`` — the handler failed on the message at the cursor.
- ``record`` — a durable ``Failed`` record was written to the recovery stream.
- ``advance`` — the read cursor advanced past a failed position.
- ``flush`` — the durable cursor checkpoint advanced (``write_position``).
- ``recover`` — the recovery pass took a position terminal; ``delivered`` says whether
  the retry delivered (``True`` = resolved) or gave up (``False`` = exhausted).
- ``crash`` — the recording harness dropped and rebuilt the subscription. A crash is a
  process event, not a code branch, so it is recorded by the harness, not emitted from
  the subscription.

``specs/check.sh`` feeds that log to TLC and confirms it is a behaviour
``Recovery.tla`` permits (see ``specs/RecoveryTrace.tla``), that it witnesses the
redelivery from a crash after the record but before the durable flush (the window
the protocol exists for), and that a seeded advance-without-record is rejected.

The recorder is inactive by default, so the subscription pays nothing on the normal
path: :func:`record` returns on its first line unless a :func:`capture` is in
progress. This mirrors :mod:`protean.utils.occ_trace`; like that module it is an
internal diagnostic seam, not part of the public surface.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Literal, TypedDict

Action = Literal[
    "handle_ok",
    "fail",
    "record",
    "advance",
    "flush",
    "recover",
    "crash",
]


class RecoveryEvent(TypedDict):
    """One observed transition of the recovery protocol.

    ``action`` is the transition; ``position`` is the global position it concerns
    (the durable cursor for ``flush``/``crash``, informational there since the model
    ignores it). ``delivered`` is meaningful only for ``recover`` — ``True`` when the
    retry resolved the position, ``False`` when it exhausted; ``None`` otherwise.
    """

    action: Action
    position: int
    delivered: bool | None


# The active log, or None when no capture is in progress. Guarded by _lock so the
# pointer swap in capture() cannot race an append. Unlike occ_trace the recovery
# recording is single-threaded (one subscription driven step by step), but the lock
# keeps the two modules' contract identical and costs nothing on the inactive path.
_lock = threading.Lock()
_events: list[RecoveryEvent] | None = None


def is_active() -> bool:
    """Whether a capture is in progress. The subscription tests this before work."""
    return _events is not None


def record(
    *,
    action: Action,
    position: int,
    delivered: bool | None = None,
) -> None:
    """Append one observed recovery transition to the active log.

    A no-op unless a :func:`capture` is in progress, so the subscription can call it
    unconditionally on the recovery path. See :class:`RecoveryEvent` for the fields.
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
            RecoveryEvent(action=action, position=position, delivered=delivered)
        )


@contextmanager
def capture() -> Iterator[list[RecoveryEvent]]:
    """Activate the recorder for the duration of the block, yielding the shared log.

    Restores the previous recorder on exit, so captures nest and an error inside the
    block cannot leave the recorder wedged on. The pointer swap is taken under the
    same lock as the appends.
    """
    global _events
    fresh: list[RecoveryEvent] = []
    with _lock:
        previous = _events
        _events = fresh
    try:
        yield fresh
    finally:
        with _lock:
            _events = previous
