# ADR-0031: A handler method persists or calls out, never both

**Status:** Accepted

**Date:** August 2026

## Context

`@handle` wraps every handler invocation in a `UnitOfWork`
(`src/protean/utils/mixins.py`), and there is no way to influence that. Since
ADR-0027 the Unit of Work is one real database transaction, so a handler that
calls an external system holds row locks and a pooled connection for the length
of that call. Version (OCC) and transient retry re-run the whole handler body, so
a retry re-issues the call.

A request came in for `@handle(SomeEvent, unit_of_work=False)`: run the handler
with no wrapping Unit of Work so it can own its own transaction boundaries and
commit sub-units independently. Working through the cases showed the request was
pointing at something real and prescribing the wrong fix, and that most of what
it asked for either already works or should not be built.

Three facts drove the decision, all verified by running rather than by reading:

1. **The Unit of Work is lazy.** `start()` opens no session. The session, and on
   SQLAlchemy the real `BEGIN`, appears at the first repository access. A handler
   method that persists nothing therefore already runs with no transaction. This
   was an accident of the implementation rather than a promise.

2. **Handler methods are already transactionally independent.** For event
   handlers and projectors, `_dispatch_handlers` loops over every matching
   handler method and each one gets its own `UnitOfWork`. One event handled by
   three methods is already three independent transactions.

3. **They are not independent in failure.** The loop propagates the first
   exception, so sibling methods are skipped, and `_handlers` is a
   `defaultdict(set)`, so which ones get skipped is arbitrary. With three methods
   where the second fails, one sibling ran and one never did.

Prior art was consulted rather than invented. Spring models this as a propagation
enum (`REQUIRED`, `REQUIRES_NEW`, `NOT_SUPPORTED`, `NESTED`) and enforces
guardrails, raising when a transactional event listener picks a propagation that
cannot work. Axon makes the Unit of Work a lifecycle with phases and has
components register work into a phase, with no opt-out. Django offers
`on_commit()`, `atomic(durable=True)` and `non_atomic_requests`, and its
`on_commit` callbacks are lost on a crash. NServiceBus is explicit that its outbox
covers outgoing messages only and does not extend to HTTP, email, or the
filesystem. Temporal records a side effect's result in history so replay returns
the recorded value instead of re-executing.

## Decision

**A handler method either persists or talks to the outside world. Not both.**

That is the whole rule, and it is what the framework teaches, checks, and
documents. Around it:

- **Guarantee: no persistence means no transaction.** A handler method that makes
  no repository access runs no transaction and holds no connection. The lazy
  session becomes a stated contract instead of an incidental optimization, which
  is what makes the rule work without any new API.

- **When a handler genuinely needs both**, because it needs an external result to
  compute the local write, it does both in one method and the transaction stays
  open for the call. The mitigation is the remote system's idempotency key, which
  is the feature that exists for exactly this, and keeping the call short. Protean
  does not build a mechanism for this case.

- **An advisory diagnostic** reports a handler method that both persists and calls
  out. It is advisory, not an error, because the previous point makes that shape
  legitimate sometimes, and a check that fires on correct code is one people learn
  to ignore. It is suppressible through the existing `suppress_checks` option.

- **A failing handler method must not skip its siblings.** Fact 3 above is a
  defect against the model this ADR states, and it is fixed rather than
  documented.

- **No ordering between handlers for the same event, ever.** If two reactions must
  happen in order, the second is not reacting to the event, it is reacting to what
  the first did, so it subscribes to an event the first raises. An ordering option
  would bury that dependency in configuration where nothing at the call site
  reveals it. An event chain puts it in the code, where correlation and causation
  IDs already trace it and each step can be tested on its own.

**No new API is added.** Everything else the request asked for already exists: the
outbox for outbound messages, `idempotent=True` for redelivery, event chains for
sequencing, and separate handler classes for full independence with their own
subscriptions and checkpoints.

## Consequences

Positive:

- The rule fits in one sentence and is checkable, both by a reader looking at a
  single method and by a static rule.
- The public surface does not grow. There is no flag, phase, scope, or journal to
  learn, and no new interaction with retry, idempotency, or nesting to reason
  about.
- Sibling handler methods become genuinely independent, matching the model users
  already have of them.
- ADR-0027 is untouched. Nothing nests, nothing commits independently, and one
  Unit of Work still maps to one use case.

Negative:

- A handler that needs an external result to compute its write still holds a
  transaction across that call. Protean offers guidance and a diagnostic rather
  than a mechanism, and an operator who ignores both will hold locks across the
  network.
- The "no persistence, no transaction" guarantee constrains the implementation.
  Opening a session eagerly is no longer free, because handler methods that only
  call out would start holding connections.
- Splitting persistence from external calls means more handler methods, and the
  data one needs from the other travels through an event rather than a local
  variable.

## Alternatives Considered

- **`@handle(Event, unit_of_work=False)`**, the original request. Rejected on
  granularity and on safety. It is Spring's `NOT_SUPPORTED` applied to a whole
  handler rather than a block, so it switches off OCC retry and the idempotency
  policy for everything else the handler does. Worse, delivery is at-least-once,
  so a handler that commits three sub-units and dies on the fourth is redelivered
  and re-applies the first three, turning a visible full rollback into a silent
  duplicate. Django's `non_atomic_requests` is the closest precedent and is safe
  for the one reason this is not: HTTP requests are not redelivered.

- **A `prepare=` phase on `@handle`**, running before the transaction and not
  replayed on retry. Rejected because the boundary is too thin to explain and it
  fails a common case: a handler that must read aggregate state to decide whether
  to make the call cannot do the deciding in a phase that may not read.

- **A journaled side effect** in the style of Temporal's `SideEffect`, recording a
  result against `(message_id, key)` so retries and redeliveries read it back.
  Rejected as complexity in the wrong place. It exists only to make the
  persist-and-call-out shape survivable, and the remote system's idempotency key
  already solves that properly, at the layer that can actually guarantee it.

- **A suspend scope**, a context manager running a block with no transaction.
  Rejected as unnecessary rather than unwanted. The "no persistence, no
  transaction" guarantee gives the same result by splitting the method, which is
  the shape we want people to write anyway. Note that ADR-0027 does not rule this
  out: its rejection of independent inner transactions rests on savepoint
  reasoning, and removing a transaction needs no savepoints.

- **Deterministic ordering for sibling handler methods.** Rejected. Making the
  order stable would legitimize depending on it, which is the coupling this ADR
  rules out. Sibling methods are independent, and the fix is that a failure in one
  no longer skips the others.
