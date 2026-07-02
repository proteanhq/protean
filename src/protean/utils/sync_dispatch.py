"""Breadth-first synchronous event dispatch.

Under ``event_processing = "sync"`` an event raised while a handler runs must be
processed *after* the current handler's UnitOfWork (and any process-manager
transition) commits — not re-entrantly in the middle of it. Re-entrant
(depth-first) dispatch breaks two things:

- a multi-step process manager cannot load its own just-persisted state for the
  next step (the transition for the current step hasn't been written yet), so
  the saga silently stalls after step 1;
- a projector for a *nested* event can run before the projector for the
  *originating* event, so a create-then-update read model raises
  ``ObjectNotFoundError`` on the update.

This module makes synchronous dispatch breadth-first via a chain-scoped FIFO
queue. Every synchronous dispatch site funnels through :func:`dispatch_events_sync`,
which enqueues ``(event, handler_cls)`` pairs and asks to drain; only the
*outermost* drain actually runs, processing the queue FIFO so each handler
commits fully before the next is dispatched. That mirrors the async engine,
where a handler's raised events re-enter as fresh outbox messages one commit at
a time. See ADR-0016.
"""

from __future__ import annotations

from collections import deque
from contextlib import contextmanager
from typing import Any, Callable, Iterable, Iterator

from protean.utils.globals import g

# Attribute names on the domain-context ``g`` (thread-local, per domain
# context — the same scope used for ``message_in_context`` and the access-log
# counters). Underscore-prefixed to match the existing ``g._access_log_*``
# convention and to avoid colliding with user state.
_QUEUE_KEY = "_sync_dispatch_queue"
_DRAINING_KEY = "_sync_dispatch_draining"


def dispatch_events_sync(
    events: Iterable[Any], handlers_for: Callable[[Any], Iterable[Any]]
) -> None:
    """Dispatch ``events`` breadth-first to the handlers ``handlers_for`` resolves.

    This is the single entry point every synchronous dispatch site should use:
    it enqueues every ``(event, handler)`` pair and then drains once. Going
    through here — rather than enqueuing/draining by hand or calling
    ``handler._handle`` directly — keeps a new dispatch site from accidentally
    forgetting to drain (events would never fire) or reintroducing depth-first
    dispatch (the bug ADR-0016 fixes).
    """
    for event in events:
        for handler_cls in handlers_for(event):
            enqueue_sync_dispatch(event, handler_cls)
    drain_sync_dispatch()


def enqueue_sync_dispatch(event: Any, handler_cls: Any) -> None:
    """Queue one ``(event, handler)`` pair for breadth-first dispatch.

    Captures the active ``message_in_context`` alongside the pair so the
    deferred drain runs the handler under the same causation/correlation context
    it would have had if dispatched immediately — preserving trace lineage
    across the reorder.
    """
    queue = getattr(g, _QUEUE_KEY, None)
    if queue is None:
        queue = deque()
        setattr(g, _QUEUE_KEY, queue)

    queue.append((event, handler_cls, g.get("message_in_context")))


def drain_sync_dispatch() -> None:
    """Drain the queue FIFO — but only at the outermost call.

    A nested call (a handler's own UnitOfWork commit re-entering here) returns
    immediately; the events it enqueued are picked up by the outermost drain
    already in progress. The queue and draining flag are cleared even if a
    handler raises, so the exception surfaces to the top-level caller ("sync
    raises") and any later work starts from a clean slate.
    """
    if getattr(g, _DRAINING_KEY, False):
        return

    setattr(g, _DRAINING_KEY, True)
    try:
        queue = getattr(g, _QUEUE_KEY, None) or ()
        while queue:
            event, handler_cls, message_context = queue.popleft()
            with _message_in_context(message_context):
                handler_cls._handle(event)
    finally:
        g.pop(_QUEUE_KEY, None)
        g.pop(_DRAINING_KEY, None)


@contextmanager
def _message_in_context(value: Any) -> Iterator[None]:
    """Set ``g.message_in_context`` to ``value`` for the block, then restore it.

    ``value`` of ``None`` means "no context" — the key is removed and restored
    rather than set to ``None`` — matching the save/restore convention used by
    the command processor and engine.
    """
    previous = g.get("message_in_context")
    _set_message_context(value)
    try:
        yield
    finally:
        _set_message_context(previous)


def _set_message_context(value: Any) -> None:
    if value is not None:
        setattr(g, "message_in_context", value)
    else:
        g.pop("message_in_context", None)
