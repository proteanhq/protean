# ADR-0025: Gap-Safe Checkpointing for `$all` Subscriptions

**Status:** Accepted

**Date:** July 2026

## Context

An `EventStoreSubscription` advances its checkpoint to the last `global_position`
it has read and reads strictly forward from there. `global_position` is a
store-wide sequence (a Postgres `bigserial` in MessageDB), and a sequence value
is *assigned* when a row is inserted but only becomes *visible* when that row's
transaction commits. Under concurrency a transaction can be assigned a lower
value and commit *after* one assigned a higher value — the classic event-sourcing
"gap problem". If the subscription has already advanced past the higher value, the
lower one, once it finally commits, is never read: a permanent, silent hole in a
projection or handler side effect, at zero apparent consumer lag.

Whether this can happen depends entirely on what the subscription reads:

- MessageDB serializes writes **within a category** with a per-category advisory
  transaction lock held until commit (its `write_message` takes
  `pg_advisory_xact_lock` on the category hash — confirmed empirically while
  scoping this change: a second same-category write blocks until the first
  commits), so a category's own `global_position` values always commit in order.
  Every ordinary subscription reads a single category (the aggregate's category,
  or one per category for a projector), so it cannot see a gap. The in-memory
  store is single-threaded and equally safe. This is the load-bearing guarantee
  that makes gating gap-safety on `$all` alone correct.
- A **`$all`** subscription reads across every category, where different categories
  hold different locks, so cross-category commits genuinely interleave out of
  order. `$all` is a supported, tested pattern (the "any event" handler, analytics
  projectors over all events), so the gap is reachable — but only there.

This decision builds directly on ADR-0024: a `$all` read must page by
`global_position`, inclusive and ordered, for a low-watermark defined in
`global_position` terms to be meaningful.

## Decision

`$all` subscriptions process with a **settle-then-process low-watermark**; every
other subscription is unchanged.

On each tick a `$all` subscription reads forward from `current_position + 1` and
processes only the **contiguous run** of `global_position` values from there. At
the first missing position it **holds** — it does not advance past a gap, so a
lower position that commits late is still read when it appears. Because a
rolled-back append permanently consumes a `global_position` (a hole that will
never fill), a gap that stays unfilled longer than **`gap_timeout_seconds`**
(default 5, configurable under `[server.event_store_subscription]`) is
**abandoned**: the watermark advances past it and processing resumes. Positions
above an unfilled gap wait until it resolves.

The common path is unaffected: when positions arrive in order (the overwhelming
majority of ticks) the whole batch is contiguous and processed immediately, with
no added latency. Only a genuine cross-category gap incurs up to
`gap_timeout_seconds` of delay for the positions stacked above it. Because the
subscription never advances its durable checkpoint past a gap, a crash-and-resume
re-reads from before the gap rather than skipping it.

## Consequences

- A `$all` subscription no longer silently loses an event to an out-of-order
  commit; two concurrent cross-category writes are both delivered, in
  `global_position` order.
- Single-category subscriptions pay nothing — the gap machinery is gated on
  `stream_category == "$all"`, and they were already safe by the per-category
  commit-order guarantee.
- `gap_timeout_seconds` is a real trade-off. Too short risks skipping a commit
  slower than the timeout (now a bounded, logged, configurable risk rather than a
  silent permanent loss); too long makes positions above an actual gap wait
  longer. Five seconds balances the two for the analytics/projection workloads
  `$all` typically serves; latency-sensitive consumers can lower it. Setting it to
  `0` (or below) abandons every gap immediately — an explicit opt-out that trades
  gap-safety back for zero added latency.
- Gap handling needs no dedup: because the subscription never advances past an
  unprocessed position, a message is never delivered twice, so correctness does
  not depend on the (optional) idempotency store.

## Alternatives Considered

- **Process eagerly and re-read a trailing window to catch late commits, deduping
  already-processed messages.** Rejected — it lowers head-of-line blocking but
  makes correctness depend on the idempotency store (optional, Redis-backed);
  settle-then-process is correct with nothing extra configured.
- **No gap handling; document `$all` as at-least-once-with-possible-gaps.**
  Rejected — a projector over `$all` silently losing an event is a data-loss bug,
  not an acceptable contract.
- **Extend MessageDB's per-category advisory lock to a global lock.** Rejected —
  it would serialize all writes store-wide (a severe throughput cost) to protect a
  read pattern that a bounded per-subscription watermark handles at no cost to
  anyone else, and it is not possible on the in-memory store.
