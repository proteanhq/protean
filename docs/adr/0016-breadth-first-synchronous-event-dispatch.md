# ADR-0016: Breadth-First Synchronous Event Dispatch

**Status:** Accepted

**Date:** July 2026

## Context

With `event_processing = "sync"`, `UnitOfWork._do_commit` consumed the events
raised in the transaction by calling `handler_cls._handle(event)` immediately,
in-stack, at commit time. This is **depth-first, re-entrant** dispatch: an event
raised *inside* a running handler is processed nested — before the current
handler's side effects, including a process manager's transition, are persisted.

Two failures follow directly from that ordering:

- **Multi-step process managers stall after step 1.** A saga's start handler
  typically dispatches the next command (`current_domain.process(cmd,
  asynchronous=False)`), which raises the next event. Under re-entrancy that
  event re-enters `_handle` for step 2 while step 1 is still running, so
  `_load_or_create` reads the PM's stream — still empty, because the start
  transition is persisted only *after* the handler returns — gets `None`, and
  silently skips the step. The saga can never advance past step 1 in sync mode.

- **Projectors can update before they create.** The same depth-first order lets
  a projector for a *nested* event run before the projector for the
  *originating* event. A read model that creates on `Requested` and updates on
  `Reserved` sees `Reserved` first and raises `ObjectNotFoundError` on the
  update's `get()`.

The asynchronous engine does not have either problem: a handler's raised events
are written to the outbox and re-enter the engine as brand-new messages, one
full commit at a time. It is already **breadth-first**. Synchronous processing —
used by tests and single-process/dev setups — should behave the same.

## Decision

Make synchronous dispatch **breadth-first** using a chain-scoped FIFO queue
(`src/protean/utils/sync_dispatch.py`).

1. **Enqueue, then drain at the outermost point.** Every synchronous dispatch
   site (`UnitOfWork._do_commit` and the three `testing.py` sites) enqueues
   `(event, handler)` pairs and calls the drain. Only the *outermost* drain runs;
   a nested call (a handler's own commit re-entering) returns immediately, and
   the events it enqueued are processed by the outer drain. The queue and the
   re-entrancy flag live on the domain-context `g`, so they survive nested
   UnitOfWork commits and re-entrant `process()` calls.

2. **Each handler commits before the next runs.** Draining FIFO means a process
   manager's transition for the current step is persisted before the next step's
   event is handled, and an originating event's projector runs before a nested
   event's projector.

3. **Preserve trace lineage.** The active `message_in_context` is captured at
   enqueue time and restored around each drained `_handle`, so causation and
   correlation are identical to before — only *when* a handler runs changes, not
   the context it runs under.

4. **No configuration flag.** Breadth-first is the only synchronous behavior.
   The prior depth-first behavior left multi-step process managers broken and
   diverged from the async engine, so there is no correct legacy behavior worth
   preserving behind a flag. This is a deliberate departure from the default
   Tier-2 "opt-in flag" path in ADR-0004; see Upgrade Notes.

## Consequences

Positive:

- Multi-step process managers work identically under sync and async dispatch.
- Projector create-before-update ordering is restored; the `ObjectNotFoundError`
  class of failure disappears.
- Synchronous and asynchronous processing converge on the same causal ordering,
  removing a "works async, breaks sync" trap for tests and dev setups.
- Trace causation/correlation is unchanged.

Negative (Tier-2 behavioral change):

- A nested `current_domain.process(sub, asynchronous=False)` now returns *before*
  its downstream cascade runs, where previously it returned *after* the entire
  nested cascade completed. Code that read a downstream side effect immediately
  after a nested `process()` call must move that read after the enclosing
  handler (and its UnitOfWork) returns. Because the change is default-on with no
  opt-out, it is called out in the Upgrade Notes below.

## Upgrade Notes

If a handler dispatches a nested command synchronously and then inspects the
result of that command's *downstream* events within the same handler, that
inspection will no longer see the cascade, because the cascade is now drained
after the handler returns:

```python
@handle(Placed, start=True, correlate="order_id")
def on_placed(self, event):
    current_domain.process(Reserve(order_id=event.order_id), asynchronous=False)
    # BEFORE (depth-first): the Reserved cascade had already run here.
    # AFTER  (breadth-first): it runs after this handler returns.
```

Move such assertions/reads out of the handler to after the top-level
`process()`/`add()` call returns. The final state after the whole chain settles
is unchanged; only mid-handler visibility of downstream effects differs. Process
managers, event handlers, and projectors require no changes — they benefit from
the fix automatically.

## Alternatives Considered

**Opt-in configuration flag (strict Tier-2).** Default to depth-first, let
operators opt into breadth-first, and flip the default over three minor
versions. Rejected: it keeps multi-step process managers broken by default, and
depth-first is not a "correct old behavior" worth preserving — it is the bug.

**Narrow process-manager-only fix.** Persist the PM transition before running the
handler body, or special-case PM re-entry. Rejected: persisting the transition
before the handler runs is semantically wrong (the transition captures
post-handler state), and it leaves the projector create-before-update bug
untouched. Breadth-first fixes both symptoms at the shared dispatch layer.

**Queue on the UnitOfWork rather than `g`.** Rejected: `UnitOfWork._messages_to_dispatch`
is per-UoW and broker-only. The queue must outlive nested UnitOfWork commits and
re-entrant `process()` calls within one domain context, so it is chain-scoped on
`g`, alongside `message_in_context`.
