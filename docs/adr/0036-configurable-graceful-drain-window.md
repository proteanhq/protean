# ADR-0036: Configurable Graceful Drain Window

**Status:** Accepted

**Date:** August 2026

**Supersedes:** ADR-0011's fixed 10-second drain window (its "hard-coded drain
window" consequence and its "Configurable drain timeout" alternative)

## Context

ADR-0011 set the engine's graceful shutdown contract and fixed the drain window
at 10 seconds. It rejected making the window configurable for one reason: an
operator could set it high during an incident, forget to reset it, and stretch
every later rolling deploy. So the bound stayed hard-coded.

That reasoning held while the only knob was the raw number, but a fixed 10
seconds is wrong for two real workloads:

- Handlers that legitimately take longer than 10 seconds, such as a batch
  projector rebuild or a slow downstream call. Under the fixed window they are
  force-cancelled on every shutdown, so a redeploy can tear a handler down
  mid-write. ADR-0011 listed this as a negative consequence and told operators
  to "split the handler or accept cancellation." Splitting is not always
  possible.
- Handlers that finish well under 10 seconds, where a shorter window lets
  deploys roll faster.

The concern behind the original rejection, set-high-and-forget, is real. It is a
guardrail to build, and this ADR adds the knob together with those guardrails.

## Decision

`server.drain_timeout` (seconds, default 10) in `domain.toml` sets how long
`Engine.shutdown()` waits for in-flight handlers to finish before force-
cancelling them. When the key is absent the engine uses 10 seconds, so existing
deployments behave exactly as they did before.

The engine validates the value at startup and refuses shapes that would silently
misbehave:

- A boolean is rejected. TOML `drain_timeout = true` would otherwise coerce to a
  1-second window, because `bool` is a subclass of `int`.
- A non-finite value (`nan`, `inf`) is rejected. `nan` slips past every range
  check since each comparison against it is false; `inf` outlives the
  supervisor's kill timeout.
- Zero or negative is rejected, since it gives no grace at all: `asyncio.wait`
  returns on the next loop step and every unfinished handler is cancelled.

Any rejected value logs a named warning and falls back to 10 seconds, so a bad
value never stops startup.

The set-high-and-forget risk is bounded, not removed:

- The default stays 10 seconds, so a deployment that never sets the key keeps
  the old behaviour.
- Under `protean server --workers N` the supervisor SIGKILLs a worker that has
  not exited within its 30-second kill timeout. The engine logs a startup
  warning when `drain_timeout` reaches that timeout, since a worker could be
  killed before it finishes draining.
- The value lives in `domain.toml` under version control. An incident-time bump
  shows up in the diff and gets reviewed like any other change.

The `/drainz` health endpoint, the other half of this change, flips the engine
into a `draining` state without shutting it down, so an orchestrator can quiesce
a pod before sending `SIGTERM`. That extends the health-check surface from
ADR-0012 and is described in the server hardening reference, so it is not
restated here.

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
  who sets a large window slows their own deploys. The version-controlled config
  and the supervisor warning are the mitigations; there is no hard cap.
- The reloader and the supervisor size their worker-termination budgets from the
  configured window, so a longer window means a longer wait before a `--reload`
  restart or a supervised shutdown gives up on a worker and kills it.

## Alternatives Considered

**Keep the window fixed (the ADR-0011 decision).** Rejected. It forces every
deployment into the same choice: force-cancel legitimate long handlers, or never
ship them. The original set-high-and-forget worry is covered by the 10-second
default, the supervisor warning, and config review, so the fixed bound buys
predictability that the knob's guardrails already provide.

**Cap the configurable value at the supervisor kill timeout.** Rejected. A
single-worker run has no supervisor and no such ceiling, so a hard cap would
reject a legitimate long window there. A warning at the boundary gives the
multi-worker operator the signal they need and leaves the single-worker case
free.

## References

- ADR-0011: Engine Shutdown and Resource Lifecycle Contract (the fixed-window
  decision this revises)
- ADR-0012: Health Check Architecture (the probe surface `/drainz` extends)
- `docs/reference/server/hardening.md` (operator-facing drain and `/drainz`
  behaviour)
