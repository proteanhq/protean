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

Each ``(event, handler_cls)`` pair is an independent reaction to a fact: under
async each handler class has its own subscription, so one class failing never
touches another. The drain gives sync the same guarantee (ADR-0031). Every pair
runs, failures are collected, and one (or a group) surfaces once the drain
finishes. An ``ExpectedVersionError`` is collected like any other failure.
When a commit calls the drain, the commit has already saved its writes, so
rerunning the command would not resolve a handler's conflict. An event
handler's or projector's own ``@handle`` wrapper retries the conflict when
version retry is enabled. One failure is excluded and ends the drain where it
is raised: a ``BaseException`` that is not an ``Exception`` (an interrupt) must
not be swallowed.
"""

from __future__ import annotations

import logging
import sys
from collections import deque
from collections.abc import Callable, Iterable, Iterator, Sequence
from contextlib import contextmanager
from typing import Any

from protean.utils.globals import g
from protean.utils.telemetry import describe_exception

logger = logging.getLogger(__name__)

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
    """Run every queued ``(event, handler)`` pair in FIFO order.

    Only the outermost call drains. A nested call, such as a handler's own
    UnitOfWork commit, returns at once, and the outermost drain runs the pairs
    it enqueued. The queue is cleared when the drain ends, even when it raises.

    Every pair runs even when an earlier one fails. Once the queue is empty, a
    single failure is raised unchanged and several are raised together as an
    ``ExceptionGroup``. This includes ``ExpectedVersionError``.

    Raises:
        BaseException: A ``BaseException`` that is not an ``Exception``, such
            as ``KeyboardInterrupt``, ends the drain where it is raised and
            propagates at once. Failures collected before it are attached to
            it as a note and logged. See ADR-0031.
    """
    if getattr(g, _DRAINING_KEY, False):
        return

    setattr(g, _DRAINING_KEY, True)
    failures: list[Exception] = []
    try:
        queue = getattr(g, _QUEUE_KEY, None) or ()
        while queue:
            event, handler_cls, message_context = queue.popleft()
            with _message_in_context(message_context):
                try:
                    handler_cls._handle(event)
                # `Exception` and not `BaseException`, so an interrupt or a
                # cancellation still stops the drain where it is raised. Keeping
                # `failures` to `Exception` also matters below: the
                # `ExceptionGroup` rejects a bare `BaseException` as a member.
                except Exception as exc:  # noqa: BLE001 - collected and re-raised below
                    failures.append(exc)
                except BaseException as exc:
                    _carry_discarded_failures(failures, exc)
                    raise

        if failures:
            if len(failures) == 1:
                # A lone failure propagates as itself rather than wrapped in a
                # one-member group, keeping its original exception type for
                # the caller.
                raise failures[0]
            raise ExceptionGroup(
                f"Synchronous dispatch: {len(failures)} handler classes failed",
                failures,
            )
    finally:
        g.pop(_QUEUE_KEY, None)
        g.pop(_DRAINING_KEY, None)


def _carry_discarded_failures(
    failures: Sequence[Exception], exc: BaseException
) -> None:
    """Attach failures collected before *exc* ended the drain early.

    The exclusion path re-raises only *exc* itself, a non-``Exception``
    ``BaseException`` such as an interrupt, so the failures gathered from earlier
    handler classes are dropped and nothing on the synchronous path reports them.
    Without this they would vanish with no log and no chain.
    """
    if not failures:
        return

    # Everything here is best-effort. A user exception with a broken ``__str__``,
    # or one whose ``__notes__`` is not a list, would otherwise raise from this
    # helper and *replace* the exception it was annotating, swallowing an
    # interrupt.
    try:
        # Described as one group rather than joined member by member, so the note
        # inherits ``describe_exception``'s length bound.
        exc.add_note(
            describe_exception(
                ExceptionGroup(
                    "Synchronous dispatch ended early; these handler-class "
                    "failures were not raised",
                    failures,
                )
            )
        )
    except Exception as note_error:  # noqa: BLE001 - must not replace the exception it annotates
        logger.debug("Could not note the discarded failures: %r", note_error)

    try:
        logger.error(
            "sync_dispatch.sibling_failures_discarded",
            extra={"discarded": len(failures)},
            exc_info=failures[0],
        )
    except Exception as log_error:  # noqa: BLE001 - logging is broken, so warn on stderr
        print(
            f"Warning: could not log {len(failures)} discarded handler failures: "
            f"{describe_exception(log_error)}",
            file=sys.stderr,
        )


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
        g.message_in_context = value
    else:
        g.pop("message_in_context", None)
