# ADR-0016: Breadth-First Synchronous Event Dispatch

**Status:** Accepted

**Date:** July 2026

## Context

With `event_processing = "sync"`, `UnitOfWork._do_commit` consumed the events
raised in the transaction by calling `handler_cls._handle(event)` immediately,
in-stack, at commit time. This is **depth-first, re-entrant** dispatch: Protean
processes an event raised *inside* a running handler at once, nested in that
handler. The nested event runs before Protean persists the current handler's
side effects, including a process manager's transition.

Two failures follow directly from that ordering:

- **Multi-step process managers stall after step 1**: A saga's start handler
  typically dispatches the next command (`current_domain.process(cmd,
  asynchronous=False)`), which raises the next event. Under re-entrancy that
  event re-enters `_handle` for step 2 while step 1 is still running.
  `_load_or_create` then reads the PM's stream. That stream is still empty,
  because the start transition is persisted only *after* the handler returns.
  `_load_or_create` gets `None`, and Protean silently skips the step. The saga
  can never advance past step 1 in sync mode.

- **Projectors can update before they create**: Under the same depth-first
  order, a projector for a *nested* event runs before the projector for the
  *originating* event. Take a read model that creates its record on `Requested`
  and updates it on `Reserved`. Its projector sees `Reserved` first and raises
  `ObjectNotFoundError` on the update's `get()`.

The asynchronous engine does not have either problem: a handler's raised events
are written to the outbox and re-enter the engine as brand-new messages, one
full commit at a time. It is already **breadth-first**. Synchronous processing
(used by tests and single-process/dev setups) should behave the same.

## Decision

Make synchronous dispatch **breadth-first** using a chain-scoped FIFO queue
(`src/protean/utils/sync_dispatch.py`).

1. **Enqueue, then drain at the outermost point**: Every synchronous dispatch
   site (`UnitOfWork._do_commit` and the three `testing.py` sites) enqueues
   `(event, handler)` pairs and calls the drain. Only the *outermost* drain
   runs. A nested call (a handler's own commit re-entering) returns
   immediately, and the outer drain processes the events it enqueued. The queue
   and the re-entrancy flag are stored on the domain-context `g`, so they
   remain available across nested UnitOfWork commits and re-entrant `process()`
   calls.

2. **Each handler commits before the next runs**: The drain processes the queue
   in FIFO order, so a process manager's transition for the current step is
   persisted before the next step's event is handled. For the same reason, an
   originating event's projector runs before a nested event's projector.

3. **Preserve trace lineage**: The dispatch code captures the active
   `message_in_context` at enqueue time and restores it around each drained
   `_handle`, so causation and correlation are identical to before. Only *when*
   a handler runs changes, not the context it runs under.

4. **Offer no configuration flag**: Breadth-first is the only synchronous
   behavior. The prior depth-first behavior left multi-step process managers
   broken and diverged from the async engine, so there is no correct legacy
   behavior worth preserving behind a flag. This is a deliberate departure from
   the release policy (ADR-0004), which by default puts a behavioral break
   (Tier 2) behind an "opt-in flag". See Upgrade Notes for what changes for
   you.

## Consequences

Positive:

- Multi-step process managers work identically under sync and async dispatch.
- Projector create-before-update ordering is restored; the `ObjectNotFoundError`
  class of failure disappears.
- Synchronous and asynchronous processing follow the same causal ordering, so
  code that works async does not break under sync in tests and dev setups.
- Trace causation/correlation is unchanged.

Negative (Tier-2 behavioral change):

- A nested `current_domain.process(sub, asynchronous=False)` now returns
  *before* its downstream cascade runs. Previously it returned *after* the
  entire nested cascade completed. If your code read a downstream side effect
  immediately after a nested `process()` call, move that read after the
  enclosing handler (and its UnitOfWork) returns. Because the change is
  default-on with no opt-out, the Upgrade Notes below describe it.

## Upgrade Notes

Suppose a handler dispatches a nested command synchronously and then, within
the same handler, inspects the result of that command's *downstream* events.
The handler no longer sees the cascade at that point, because the drain runs
the cascade after the handler returns:

```python
@handle(Placed, start=True, correlate="order_id")
def on_placed(self, event):
    current_domain.process(Reserve(order_id=event.order_id), asynchronous=False)
    # BEFORE (depth-first): the Reserved cascade had already run here.
    # AFTER  (breadth-first): it runs after this handler returns.
```

Move such assertions/reads out of the handler to after the top-level
`process()`/`add()` call returns. The final state after the whole chain settles
is unchanged; only mid-handler visibility of downstream effects differs.
Process managers, event handlers, and projectors that do not read downstream
effects mid-handler require no changes. They benefit from the fix
automatically.

## Alternatives Considered

**Ship breadth-first behind an opt-in configuration flag, as the release policy
(ADR-0004) prescribes for a behavioral break (Tier 2).** Default to depth-first
and let operators opt into breadth-first. Flip the default over three minor
versions. Rejected: it keeps multi-step process managers broken by default.
Depth-first is not a "correct old behavior" worth preserving. It is the bug.

**Fix only the process manager.** Persist the PM transition before running the
handler body, or special-case PM re-entry. Rejected: the transition captures
post-handler state, so persisting it before the handler runs is semantically
wrong. This fix also leaves the projector create-before-update bug untouched.
The breadth-first queue in the shared dispatch layer fixes both symptoms.

**Queue on the UnitOfWork rather than `g`.** Rejected:
`UnitOfWork._messages_to_dispatch` is per-UoW and broker-only. The queue must
last across nested UnitOfWork commits and re-entrant `process()` calls within
one domain context. So it is stored on `g`, alongside `message_in_context`, and
scoped to the whole chain of handlers in that context.
