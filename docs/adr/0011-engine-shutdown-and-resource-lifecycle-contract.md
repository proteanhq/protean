# ADR-0011: Engine Shutdown and Resource Lifecycle Contract

| Field | Value |
|-------|-------|
| **Status** | Accepted |
| **Date** | 2026-04-23 |
| **Author** | Subhash Bhushan |

## Context

Before the 5.1 hardening work, `Engine.shutdown()` was optimistic: it
called `subscription.shutdown()` on each subscription, then stopped the
event loop. Three problems surfaced in production:

1. **Leaked sockets and background threads.** Brokers, caches, event
   stores, and providers had no explicit `close()` contract. Redis
   clients stayed bound to ports until garbage collection; SQLAlchemy
   engines released their pools at process exit instead of at domain
   teardown. Long-running test suites that created and discarded
   domains exhausted file descriptors.
2. **No drain window.** In-flight handlers were abandoned when the
   loop stopped. A handler midway through committing a UoW could be
   torn down between the database write and the event-store append,
   leaving the aggregate and its event log in disagreement.
3. **No signal to load balancers.** The engine had no health probe,
   so Kubernetes rolling deploys relied on `terminationGracePeriodSeconds`
   alone to avoid dropping in-flight traffic. There was no way for
   the engine to say "I'm draining; don't send me more work."

`Domain.close()` did not exist. Tests that spun up ad-hoc domains had
no way to tear them down cleanly, which the test suite worked around
with per-suite fixtures that bypassed adapter lifecycles entirely.

## Decision

We will treat engine shutdown as a four-step contract, and we will
expose `Domain.close()` as a public API that tests, tooling, and
embedders can call directly.

**The shutdown sequence:**

1. **Fail readiness probes immediately.** `Engine.shutdown()` sets
   `shutting_down = True` and stops the embedded health HTTP server.
   `/readyz` returns `503` with `{"status": "unavailable"}` from this
   point forward. Load balancers and service meshes pull the pod out
   of rotation before subscriptions stop.
2. **Stop subscriptions.** Every `StreamSubscription`,
   `BrokerSubscription`, `OutboxProcessor`, and `DLQMaintenanceTask`
   receives `shutdown()`. Backend-specific cleanup runs here —
   positions persist, consumer-group state flushes. Subscriptions
   return from `shutdown()` when they have stopped accepting new
   messages; they do not wait for in-flight handlers.
3. **Drain in-flight handlers with a 10-second bound.** The engine
   gathers every asyncio task that is not itself, with `timeout=10.0`.
   Tasks that finish within the window complete normally; tasks still
   running after the window are cancelled. The bound is hard-coded,
   not configurable.
4. **Close the domain.** `domain.close()` runs. Each adapter registry
   (`event_store`, `brokers`, `caches`, `providers`) is closed in
   reverse initialisation order. Every `close()` is wrapped in
   `try/except`: one adapter's failure to close cannot prevent the
   rest from closing.

**The `Domain.close()` contract:**

- Order: `event_store → brokers → caches → providers`. Dependents close
  before dependencies, so a handler completing a commit during close
  does not find its repository's connection pool gone.
- Per-adapter error isolation: each `close()` is wrapped in
  `try/except`. Exceptions are logged but do not propagate, and do not
  prevent subsequent adapters from closing.
- Idempotence: each registry guards against double-close internally,
  but individual adapter behaviour on repeated `close()` is
  adapter-defined. Callers should not call `Domain.close()` more than
  once per domain instance.
- Custom adapters inherit a no-op `close()` on `BaseBroker`,
  `BaseCache`, and the provider/event-store base classes. Adapters
  that hold sockets, file handles, or background threads must
  override.

**Kubernetes contract:**

- Set `terminationGracePeriodSeconds >= 15` to cover the 10-second
  drain plus adapter close time.
- Use a `preStop` sleep (typically `5s`) before `SIGTERM` to let the
  load balancer observe the `/readyz` `503` before the engine starts
  stopping subscriptions.

## Consequences

**Positive:**

- In-flight handlers get a bounded, predictable drain window instead
  of an abrupt cancel. Aggregates and event logs stay in agreement
  across rolling deploys.
- `Domain.close()` is a first-class API. Tests and tooling that
  create domains on demand can tear them down cleanly. The test
  suite no longer has to bypass adapter lifecycles.
- Socket, file-descriptor, and thread leaks are eliminated by
  default — every adapter now has a real `close()` hook.
- Load balancers pull pods out of rotation before handlers are
  disturbed, because readiness fails in step 1 while handlers drain
  in step 3.
- One adapter's misbehaviour on close (e.g., a network error
  reaching Redis) cannot prevent the rest of the domain from closing.

**Negative:**

- Shutdown is no longer instantaneous. A worst-case shutdown takes
  up to 10 seconds plus adapter close time. Developers running the
  engine under a process manager with a low `TimeoutStopSec` must
  raise it.
- The 10-second drain window is hard-coded. A workload with a
  handler that routinely takes longer must split the handler or
  accept cancellation under shutdown. We chose to keep the bound
  fixed rather than make it configurable to avoid incident scenarios
  where an operator sets it to a high value and delays deploys
  indefinitely.
- Custom adapters that ignored lifecycle before must now implement
  `close()` if they hold resources. The no-op default keeps the
  common case backward-compatible.
- `Domain.close()` silently swallows per-adapter exceptions. Callers
  cannot rely on it to surface adapter-level failures; they must
  consult logs to diagnose a close problem.

## Alternatives Considered

**Configurable drain timeout.** Rejected. The operational value of a
predictable upper bound outweighs the flexibility of tuning. A
configurable drain invites operators to set it to five minutes during
an incident and then forget to reset it, stretching subsequent rolling
deploys.

**Strict reverse-LIFO tracking of adapter initialisation.** Considered
and rejected. The actual initialisation order within a domain is
`providers → event_store → brokers → caches` (providers must exist
before event stores that depend on them). Rather than maintain a
runtime stack, we close in the inverse of that canonical order:
`event_store → brokers → caches → providers`. This is mechanically
equivalent and simpler to reason about.

**Fail-fast on adapter close errors.** Rejected. One broker failing to
close cleanly should not prevent the event store from flushing its
final state. Per-adapter `try/except` with logged errors is the
pragmatic choice; callers who need to assert clean close can read the
logs.

**Graceful SIGHUP reload.** Deferred. `SIGHUP` currently triggers the
same shutdown path as `SIGTERM`. A true reload — close subscriptions,
re-read config, recreate adapters, restart subscriptions — is a
separate feature that can be added without changing this contract.

## References

- `docs/guides/server/hardening.md` — operational guidance for K8s
  probe wiring, `terminationGracePeriodSeconds`, and process managers.
- `docs/reference/server/hardening.md` — reference catalogue for the
  shutdown sequence and `Domain.close()` per-adapter semantics.
- `docs/concepts/async-processing/engine.md` — shutdown sequence
  diagram and invariants.
