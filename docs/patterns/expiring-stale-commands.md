# Expiring Stale Commands

## The Problem

A command expresses an *intent* to change state — and many intents are only
valid for a window of time. Consider:

- "Charge this card before the checkout session expires."
- "Apply this price quote, valid for 5 minutes."
- "Send the one-time passcode" — useless once the user has given up.

In an asynchronous system, a command can sit in a queue far longer than its
intent remains valid: a deploy pauses workers, a backlog drains slowly, an
outage recovers and replays hours of queued work. When the handler finally
runs, executing the command may be worse than doing nothing — a charge against
an abandoned cart, a passcode for a session that no longer exists.

Protean lets a command carry a **deadline**. If the deadline has passed by the
time a handler is about to execute, the command is not run. See the
[Deadlines and Timeouts](../guides/change-state/commands.md#deadlines-and-timeouts)
guide for the mechanics; this pattern covers *when* and *why*.

---

## Expiry Is a Delivery Concern, Not a Domain Rule

When a command expires, **nothing happens to the domain**: no aggregate is
loaded, no invariant is evaluated, no event is raised. The model stays exactly
as it was. Expiry is therefore not a domain-rule violation — it is a policy at
the *delivery boundary*, deciding whether stale work is allowed to reach the
model at all.

This matters for how you reason about it. A `CommandExpiredError` is not the
same kind of thing as a business-rule failure like `InsufficientStock`. The
latter says "the model refused this change"; the former says "this change never
got a chance to be attempted." Don't model expiry as a domain event or bake it
into aggregate logic — keep it at the edge, where `domain.process()` and the
engine live.

The real risk expiry introduces is **lost intent**: the requested change simply
won't happen, and *something* may need to know. Whether that "something" is the
caller, an operator, or a compensating process is a business decision — which
is exactly why Protean makes expiry *observable* rather than deciding for you.

---

## The Synchronous / Asynchronous Asymmetry

The same deadline behaves differently depending on how the command is
processed, and the difference is intentional:

| | Synchronous | Asynchronous |
|---|---|---|
| Contract | "Fail fast, caller decides" | "Don't run stale work" |
| Feedback | `CommandExpiredError` raised **to the caller**, in-context | Caller already received an ack and has moved on |
| Trace of the attempt | Rejected **before** the event-store write — no record of a half-attempt | Command was stored & acked; later skipped in the queue |
| Who learns it was lost | The caller, synchronously | Operators, via metric + trace |

**Synchronous** processing keeps the caller in the loop: they are still holding
the request, so raising lets them retry with a fresh deadline, fail the user's
operation, or choose a fallback. This is the strong-feedback path.

**Asynchronous** processing has no one to tell — the caller got a position back
the moment the command was stored. So the engine acknowledges the expired
command (its read position advances, so it is **not** retried — a retry would
only expire again) and records it for operators rather than raising into the
void. Reliability here comes from *observability*, not from an exception.

---

## Make Async Expiry Observable

Because async expiry silently drops intent, treat its telemetry as
load-bearing:

- The `protean.command.expired` counter (labelled by `command_type`)
  increments on every expiry, sync or async. **Alert on it** if dropped
  commands have business consequences.
- A `handler.skipped` trace event is emitted with the command type and the
  exceeded deadline, so an expired command is visible in the lifecycle view
  rather than vanishing.

If an expired command needs *active* recovery — notifying a customer, releasing
a hold — react to it explicitly (e.g. a monitor on the metric, or a
[process manager](coordinating-long-running-processes.md) that compensates).
The framework deliberately stops at "observable"; compensation is a domain
decision.

---

## Deadlines Bound Staleness, Not Failure

A deadline answers "is this still worth doing?" — it does **not** make
processing more reliable on its own. The complete picture pairs three
mechanisms:

- **Deadline** — don't execute work that is no longer valid.
- **[Retry with backoff](../guides/change-state/command-handlers.md#error-handling)** —
  recover from transient faults. Retries should respect the deadline: stop
  retrying once it has passed.
- **Dead-lettering** — quarantine what can neither succeed nor expire cleanly.

Reaching for a deadline to "stop runaway retries" is the wrong tool — that is
the retry policy's job. Use a deadline only when the *intent itself* has a
validity window.

---

## Prefer Opt-In; Default With Care

Protean ships with **no default deadline**: commands never expire unless asked
to. This is deliberate. A surprise global timeout silently discards valid
intent during exactly the moments you most want durability — deploys, backlogs,
recovery. Commands that sit in a queue across a deploy and then process
correctly are a *feature*, not a bug.

When you do want blanket protection, opt in at the narrowest scope that fits:

1. **Per command** — pass `deadline`/`timeout` to `domain.process()` for
   intents with a genuine, specific validity window. The clearest signal.
2. **Per handler** — `@domain.command_handler(timeout=...)` when every command
   for an aggregate shares a latency budget.
3. **Per domain** — `command_default_timeout` as a last-resort safety net.

Set the narrowest one that expresses the real rule. A domain-wide default is a
blunt instrument; let specific commands and handlers refine it.

---

## Related

- [Commands → Deadlines and Timeouts](../guides/change-state/commands.md#deadlines-and-timeouts) — how to set deadlines.
- [Command Idempotency](command-idempotency.md) — the complementary "ran more than once" problem.
- [Classify Async Processing Errors](classify-async-processing-errors.md) — distinguishing expected outcomes from genuine failures.
