# Expiring Stale Commands

## The Problem

A command expresses an *intent* to change state. Many intents are valid only
for a window of time. Consider:

- "Charge this card before the checkout session expires."
- "Apply this price quote, valid for 5 minutes."
- "Send the one-time passcode". Useless once the user has given up.

In an asynchronous system, a command can sit in a queue far longer than its
intent remains valid: a deploy pauses workers, a backlog drains slowly, an
outage recovers and replays hours of queued work. When the handler finally
runs, executing the command may be worse than doing nothing. Examples include a
charge against an abandoned cart and a passcode for a session that has ended.

Protean lets a command carry a **deadline**. If the deadline has passed by the
time a handler is about to execute, the command is not run. See the [Deadlines
and Timeouts](../guides/change-state/commands.md#deadlines-and-timeouts) guide
for the mechanics. This page explains *when* and *why* to use a deadline.

---

## Expiry Is a Delivery Concern, Not a Domain Rule

When a command expires, **nothing happens to the domain**: no aggregate is
loaded, no invariant is evaluated, no event is raised. The model stays exactly
as it was. Expiry is therefore not a domain-rule violation. It is a policy at
the *delivery boundary*, deciding whether stale work is allowed to reach the
model at all.

The difference between a delivery policy and a domain rule matters for how you
reason about expiry. A `CommandExpiredError` is not the same kind of thing as a
business-rule failure like `InsufficientStock`. `InsufficientStock` says "the
model refused this change". `CommandExpiredError` says "this change never got a
chance to be attempted."" Don't model expiry as a domain event or put it in
aggregate logic. Check expiry at the delivery boundary, in `domain.process()`
and the engine.

The real risk of expiry is **lost intent**: the requested change won't happen.
*Something* may need to know that the change was lost. The business decides
whether that "something" is the caller, an operator, or a compensating process.
That is exactly why Protean makes expiry *observable* rather than deciding for
you.

---

## The Synchronous / Asynchronous Asymmetry

The same deadline behaves differently in synchronous and asynchronous
processing. Protean does this on purpose:

| | Synchronous | Asynchronous |
|---|---|---|
| Contract | "Fail fast, caller decides" | "Don't run stale work" |
| Feedback | `CommandExpiredError` raised **to the caller**, in-context | Caller already received an ack and has moved on |
| Trace of the attempt | Rejected **before** the event-store write; no record of a half-attempt | Command was stored & acked; later skipped in the queue |
| Who learns it was lost | The caller, synchronously | Operators, via metric + trace |

**Synchronous** processing tells the caller directly. The caller is still
waiting on the request, so the raised error lets them retry with a fresh
deadline, fail the user's operation, or choose a fallback. This is the
strong-feedback path.

**Asynchronous** processing has no one to tell, the caller got a position back
the moment the command was stored. So the engine acknowledges the expired
command and records it for operators instead of raising an error. The engine
advances the command's read position and does **not** retry it, since a retry
would only expire again. Reliability here comes from *observability*, not from
an exception.

---

## Make Async Expiry Observable

Because async expiry silently drops intent, you need to monitor its telemetry:

- The `protean.command.expired` counter (labelled by `command_type`)
  increments on every expiry, sync or async. If dropped commands have business
  consequences, **alert on it**.
- The engine emits a `handler.skipped` trace event with the command type and
  the exceeded deadline, so an expired command appears in the lifecycle view
  instead of vanishing.

If an expired command needs *active* recovery (notifying a customer, releasing
a hold) react to it explicitly (e.g. a monitor on the metric, or a [process
manager](coordinating-long-running-processes.md) that compensates). The
framework deliberately stops at "observable"; compensation is a domain
decision.

---

## Deadlines Bound Staleness, Not Failure

A deadline lets you answer "is this still worth doing?". It does **not** make
processing more reliable on its own. You get complete behaviour by combining
three mechanisms:

- **Deadline**: Don't execute work that is no longer valid.
- **[Retry with backoff](../guides/change-state/command-handlers.md#error-handling)**:
  recover from transient faults. Retries should respect the deadline: once it
  has passed, stop retrying.
- **Dead-lettering**: Quarantine what can neither succeed nor expire cleanly.

Don't use a deadline to "stop runaway retries". That is the retry policy's job.
Use a deadline only when the *intent itself* has a validity window.

---

## Prefer Opt-In; Default With Care

Protean ships with **no default deadline**: commands never expire unless asked
to. This is deliberate. A surprise global timeout silently discards valid
intent during exactly the moments you most want durability, deploys, backlogs,
recovery. When commands wait in a queue during a deploy and then process
correctly, the system is working as designed.

When you do want commands to expire, opt in at the narrowest possible scope:

1. **Per command**: Pass `deadline`/`timeout` to `domain.process()` for
   intents with a genuine, specific validity window. This scope shows the
   intent most clearly to readers of the code.
2. **Per handler**: `@domain.command_handler(timeout=...)` when every command
   for an aggregate shares a latency budget.
3. **Per domain**: `command_default_timeout` as a last-resort safety net.

Set the narrowest one that expresses the real rule. A domain-wide default is a
too coarse on its own; let specific commands and handlers refine it.

---

## Related

- [Commands → Deadlines and Timeouts](../guides/change-state/commands.md#deadlines-and-timeouts): How to set deadlines.
- [Command Idempotency](command-idempotency.md): The complementary "ran more than once" problem.
- [Classify Async Processing Errors](classify-async-processing-errors.md): Distinguishing expected outcomes from genuine failures.
