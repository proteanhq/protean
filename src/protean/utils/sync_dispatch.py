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
finishes. Two failures are excluded and end the drain where they are raised, for
the same reasons they are in :func:`~protean.utils.mixins.HandlerMixin._dispatch_handlers`:
an ``ExpectedVersionError`` must reach the enclosing Unit of Work's commit as
itself so version retry still fires, and a ``BaseException`` that is not an
``Exception`` (an interrupt) must not be swallowed.
"""

from __future__ import annotations

import logging
from collections import deque
from collections.abc import Callable, Iterable, Iterator, Sequence
from contextlib import contextmanager, suppress
from typing import Any

from protean.exceptions import ExpectedVersionError
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
    """Drain the queue FIFO — but only at the outermost call.

    A nested call (a handler's own UnitOfWork commit re-entering here) returns
    immediately; the events it enqueued are picked up by the outermost drain
    already in progress. The queue and draining flag are cleared even if a
    handler raises, so the exception surfaces to the top-level caller ("sync
    raises") and any later work starts from a clean slate.

    A failing handler class no longer aborts the drain. Each ``(event,
    handler_cls)`` pair is an independent reaction, so every one runs and
    failures are collected: a single failure surfaces unchanged, and several are
    raised together as an ``ExceptionGroup``. An ``ExpectedVersionError`` and a
    non-``Exception`` ``BaseException`` are the two exclusions — they end the
    drain where they are raised and propagate at once (see the module docstring
    and ADR-0031). Failures gathered before either one are attached to it as a
    note and logged, since nothing downstream would otherwise report them.
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
                except ExpectedVersionError as exc:
                    # Not collected. Grouping it would hide it from the enclosing
                    # Unit of Work's commit, which classifies by exception type,
                    # so the conflict would surface as a TransactionError and the
                    # version retry that resolves it would never fire.
                    _carry_discarded_failures(failures, exc)
                    raise
                # `Exception` and not `BaseException`, so an interrupt or a
                # cancellation still stops the drain where it is raised. Keeping
                # `failures` to `Exception` also matters below: the
                # `ExceptionGroup` rejects a bare `BaseException` as a member.
                except Exception as exc:
                    failures.append(exc)
                except BaseException as exc:
                    _carry_discarded_failures(failures, exc)
                    raise

        if failures:
            if len(failures) == 1:
                # A lone failure propagates as itself rather than wrapped in a
                # one-member group, keeping its original exception type for the
                # enclosing commit to classify.
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

    Each exclusion path re-raises only *exc* itself — a version conflict kept as
    ``ExpectedVersionError`` for the commit's classification, or a non-``Exception``
    ``BaseException`` interrupt — so the failures gathered from earlier handler
    classes are dropped and nothing on the synchronous path reports them. Without
    this they would vanish with no log and no chain.
    """
    if not failures:
        return

    # Everything here is best-effort. A user exception with a broken ``__str__``,
    # or one whose ``__notes__`` is not a list, would otherwise raise from this
    # helper and *replace* the exception it was annotating, swallowing an
    # interrupt or destroying the ExpectedVersionError exclusion above.
    with suppress(Exception):
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

    with suppress(Exception):
        logger.error(
            "sync_dispatch.sibling_failures_discarded",
            extra={"discarded": len(failures)},
            exc_info=failures[0],
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
