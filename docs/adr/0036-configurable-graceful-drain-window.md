# ADR-0036: Configurable Graceful Drain Window

**Status:** Accepted

**Date:** August 2026

**Supersedes:** ADR-0011's fixed 10-second drain window (its "hard-coded drain
window" consequence and its "Configurable drain timeout" alternative)

## Context

Under ADR-0011, the engine follows a graceful shutdown contract with a drain
window fixed at 10 seconds. The authors of ADR-0011 rejected a configurable
window for one reason: an operator could set it high during an incident, forget
to reset it, and lengthen every later rolling deploy. So the bound stayed
hard-coded.

That reasoning was sound while the only setting was the raw number, but a fixed
10 seconds is wrong for two real workloads:

- Handlers that legitimately take longer than 10 seconds, such as a batch
  projector rebuild or a slow downstream call. Under the fixed window they are
  force-cancelled on every shutdown, so a redeploy can tear a handler down
  mid-write. The authors of ADR-0011 listed this as a negative consequence.
  They told operators to "split the handler or accept cancellation."" An
  operator cannot always split the handler.
- Handlers that finish well under 10 seconds, where a shorter window lets
  deploys roll faster.

The concern behind the original rejection, set-high-and-forget, is real. The
fix for that concern is a set of safety checks. Protean adds the configurable
window and those safety checks in the same change.

## Decision

`server.drain_timeout` (seconds, default 10) in `domain.toml` sets how long
`Engine.shutdown()` waits for in-flight handlers to finish before force-
cancelling them. When the key is absent, the engine uses 10 seconds. Existing
deployments therefore behave exactly as they did before.

The engine validates the value at startup and refuses shapes that would silently
misbehave:

- A boolean is rejected. TOML `drain_timeout = true` would otherwise coerce to a
  1-second window, because `bool` is a subclass of `int`.
- A non-finite value (`nan`, `inf`) is rejected. `nan` passes every range
  check, because each comparison against it is false. `inf` is longer than the
  supervisor's kill timeout.
- Zero or negative is rejected, since it gives no grace at all: `asyncio.wait`
  returns on the next loop step and every unfinished handler is cancelled.

For any rejected value, the engine logs a named warning and falls back to 10
seconds, so a bad value never stops startup.

The risk that an operator sets the window high and forgets to reset it remains,
but three safeguards bound it:

- The default stays 10 seconds, so a deployment that never sets the key keeps
  the old behaviour.
- Under `protean server --workers N` the supervisor SIGKILLs a worker that has
  not exited within its 30-second kill timeout. When `drain_timeout` reaches
  that timeout, the engine logs a startup warning. At that value the supervisor
  could kill a worker before the worker finishes draining.
- The `drain_timeout` value is stored in `domain.toml`, which is under version
  control. An increase made during an incident appears in the diff, where
  reviewers check it like any other change.

This change also adds the `/drainz` health endpoint. A call to `/drainz` puts
the engine into a `draining` state without shutting it down, so an orchestrator
can quiesce a pod before sending `SIGTERM`. The `/drainz` endpoint adds to the
health-check endpoints defined in the health check decision (ADR-0012). The
server hardening reference describes `/drainz`, so this ADR does not restate
it.

## Consequences

**Positive:**

- Workloads with legitimately long handlers can raise the window. They no longer
  have to split every long handler or accept a mid-write cancellation on each
  deploy.
- Fast workloads can shorten the window and roll deploys faster.
- Invalid values are caught at startup with a named warning, so a typo changes
  the log, not the shutdown timing.

**Negative:**

- The predictable upper bound ADR-0011 valued is now per-deployment. An operator
  who sets a large window slows their own deploys. The version-controlled
  config and the supervisor warning reduce this risk. Protean sets no hard cap.
- The reloader and the supervisor size their worker-termination budgets from
  the configured window. With a longer window, a `--reload` restart or a
  supervised shutdown waits longer before it kills a worker that has not
  exited.

## Alternatives Considered

**Keep the window fixed (the ADR-0011 decision).** Rejected. It forces every
deployment into the same choice: force-cancel legitimate long handlers, or
never ship them. Three safeguards already limit the original risk that an
operator sets the window high and forgets it: the 10-second default, the
supervisor warning, and config review. A fixed window adds no predictability
beyond what those safeguards give.

**Cap the configurable value at the supervisor kill timeout.** Rejected. A
single-worker run has no supervisor and no such ceiling, so a hard cap would
reject a legitimate long window there. With a warning when the window reaches
the kill timeout, an operator who runs several workers learns that the
supervisor could kill a worker mid-drain. An operator who runs a single worker
can still set a long window.

## References

- ADR-0011: Engine Shutdown and Resource Lifecycle Contract (the fixed-window
  decision this revises)
- ADR-0012: Health Check Architecture (the health-check endpoints that
  `/drainz` adds to)
- `docs/reference/server/hardening.md` (operator-facing drain and `/drainz`
  behaviour)
