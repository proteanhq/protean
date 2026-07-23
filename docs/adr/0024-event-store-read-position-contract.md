# ADR-0024: Event Store Read Position Contract

**Status:** Accepted

**Date:** July 2026

## Context

`BaseEventStore.read(stream_name, position, no_of_messages)` is the single read
primitive behind every consumer that pages through the store: the
`EventStoreSubscription` engine, projections and projectors, the outbox
reconciliation sweep, the observatory timeline, and the `protean events` CLI. All
of these track their progress by **`global_position`** — the store-wide,
monotonically increasing ordinal assigned to every message — and read the next
page from `last_global_position + 1`.

The `position` argument, however, meant different things depending on the stream
name and the adapter:

- A **specific stream** (`category-id`, e.g. `order-123`) is naturally paged by
  its **per-stream** ordinal — the version within that one stream — which is what
  aggregate loading and snapshotting need.
- A **category** (`order`) or **`$all`** read spans many streams, so the only
  ordering that is meaningful across them is `global_position`.

The two adapters disagreed. MessageDB keyed **category** reads on `global_position`
(`get_category_messages` filters `global_position >= position`), but read **`$all`**
with a strict, unordered `global_position > position LIMIT n` — skipping the first
position and returning an arbitrary page. The **memory** adapter keyed *both*
category and `$all` reads on the **per-stream** ordinal and sorted by it. A
consumer paging by `global_position` then filtered the per-stream ordinal by a
global value and read the wrong page — most often nothing at all, at zero
apparent lag. This was masked because most reads are *full* reads from
`position = 0`, where `>= 0` matches everything regardless of the key; it surfaced
on any *paginated* read (`position > 0`) — always for a multi-stream category, and
even for a single stream once a subscription advanced its cursor and re-read from
`current + 1` (the per-stream ordinal is 0-indexed while `global_position` is
1-indexed, so the two never line up on a re-read).

Because the common test setup does a single full read, the divergence survived
undetected and made it impossible to reason about — or deterministically test —
any `global_position`-ordered behavior on the memory adapter.

## Decision

We define one read-position contract that every event store adapter must honor:

- A **specific-stream** read (`stream_name` contains an id, i.e. `category-id`)
  is paged by the **per-stream position**, inclusive of `position`, ordered
  ascending by that position.
- A **category** read (`stream_name` is a bare category) and an **`$all`** read
  are paged by **`global_position`**, **inclusive** of `position`
  (`global_position >= position`), ordered ascending by `global_position`.

"Inclusive" is uniform so that consumers page from `last_global_position + 1`
without per-adapter off-by-one handling. The memory adapter now filters and orders
category/`$all` reads by `global_position`; the MessageDB adapter reads `$all`
with an inclusive, `global_position`-ordered statement (its category reads already
satisfied the contract).

## Consequences

- Subscriptions, projections, and the outbox reconciliation sweep behave the same
  on the memory and MessageDB adapters, so the memory adapter is a faithful,
  Docker-free test double for `global_position`-ordered behavior. This is a
  prerequisite for gap-safe `$all` checkpointing (see #1088).
- A subscriber over a **multi-stream category** — or over `$all` — now reads the
  correct, contiguous, globally-ordered page instead of silently reading nothing.
- The outbox reconciliation tail scan (`read("$all", position=tail - limit + 1)`)
  now includes the boundary position it intends to inspect, rather than skipping
  it.
- The memory adapter carries `global_position` as a distinct, monotonic field
  (it already did); the read path now depends on it, so an adapter that fails to
  assign a meaningful `global_position` cannot satisfy the category/`$all`
  contract. This is the correct constraint: a global order is exactly what these
  reads require.
- No deprecation or compatibility flag is warranted: this corrects a bug (the
  memory adapter returned wrong or missing pages; the MessageDB `$all` read was
  exclusive and unordered) rather than changing a supported contract. The
  `global_position`-ordered, inclusive semantics were already the de facto
  behaviour of MessageDB category reads, which every consumer relies on.

## Alternatives Considered

- **Make `$all` exclusive (`> position`) everywhere and have consumers page from
  `last_global_position`.** Rejected — category reads were already inclusive, and
  aligning on inclusive keeps one rule for every stream kind and matches how
  consumers already compute `last + 1`.
- **Leave the memory adapter keyed on the per-stream ordinal and forbid
  multi-stream categories in tests.** Rejected — it entrenches a silent
  divergence from the production adapter and blocks deterministic testing of the
  behavior that matters most (ordered, gapless category/`$all` consumption).
