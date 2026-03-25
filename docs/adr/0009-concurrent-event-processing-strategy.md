# ADR-0009: Concurrent Event Processing Strategy

| Field | Value |
|-------|-------|
| **Status** | Accepted |
| **Date** | 2026-03-24 |
| **Author** | Subhash Bhushan |

## Context

A production incident in a HubSpot integration exposed a class of
concurrency bugs in event-driven systems. Two webhooks -- Client Creation
(CC) and Client-Contact Association Change (CCA) -- fired in rapid
succession. Two workers picked up these events concurrently. The CC
handler began creating a Client aggregate. Simultaneously, the CCA
handler looked for the Client, didn't find it yet (CC hadn't committed),
and created its own copy. Result: duplicate Client records.

This triggered a thorough analysis of how Protean handles concurrent
event processing. The analysis identified four problem classes:

1. **Concurrent entity creation** -- multiple events trigger "find or
   create" logic for the same aggregate
2. **Concurrent aggregate mutation** -- multiple events modify the same
   aggregate simultaneously
3. **Causal dependency violation** -- event B depends on side effects of
   event A, but B executes before A's effects are visible
4. **Duplicate processing** -- the same event is delivered twice due to
   at-least-once delivery semantics

An industry survey of Axon (Java), Eventuous (.NET), Marten (.NET), and
Wolverine (.NET) revealed three common characteristics in frameworks that
handle concurrency well: they make the aggregate the serialization
boundary, provide OCC as a safety net, and surface the concurrency model
as an explicit developer decision.

The question was whether Protean needed new infrastructure (partitioned
streams, handler-level idempotency stores, repository upsert primitives,
new aggregate Meta options) or whether the existing building blocks
already address these problem classes.

## Decision

**Protean already provides the building blocks for safe concurrent event
processing. The framework will not add new concurrency infrastructure in
the near term. Instead, it will fix the atomic race condition in
existing OCC, add a lint rule for a common structural smell, and publish
a connective pattern document.**

Specifically:

### 1. OCC is always-on, not opt-in

Every aggregate already has a `_version` field (auto-managed,
starts at -1). The DAO's `_validate_and_update_version()` runs on every
save and raises `ExpectedVersionError` on mismatch. The `@handle`
decorator retries with exponential backoff (3 retries, 50ms-1s,
configurable via `[server.version_retry]`).

We will **not** add a `concurrency_strategy = "optimistic"` Meta option.
OCC is a correctness mechanism, not a configuration choice. Adding an
opt-in would imply that running without version checking is a valid
option -- it is not.

The existing atomic race condition (SELECT-compare-UPDATE instead of
conditional UPDATE) will be fixed in 5.1 #793. This is a bug fix in
existing infrastructure, not new infrastructure.

### 2. No `find_or_create` repository primitive

`find_or_create` pushes creation logic to the database level, bypassing
aggregate constructors, invariant checking, and event raising. This
conflicts with Protean's design philosophy: "Validation lives in the
domain layer (invariants), not the database layer."

The DDD-correct solutions for creation races are:

- **Process Manager**: coordinates the flow when events have causal
  dependencies (CC must complete before CCA can act)
- **Combine into a single handler**: if both events target the same
  aggregate, a single handler serializes processing naturally
- **Unique constraints + retry**: the database prevents duplicates
  via unique constraints; `ExpectedVersionError` retry handles the
  transient conflict

### 3. No framework-level event handler idempotency

We considered adding `idempotent_by` on event handlers with a
framework-managed idempotency store, but decided against it because:

- Idempotency is inherently a business-logic concern -- the "right"
  deduplication strategy depends on the operation (set-based,
  dedup-tracked, upsert)
- Protean already has comprehensive pattern documentation for
  idempotent event handlers (600+ lines covering three strategies)
- Command idempotency via `IdempotencyStore` is already built for the
  submission boundary where framework-level dedup makes sense

### 4. `sequential_by` deferred to R4

Within-handler sequential processing by partition key (`sequential_by`)
is a legitimate feature, but the simpler solutions (PM, combine handlers,
OCC retry) handle the vast majority of cases. The infrastructure changes
required (partitioned streams, modified event publishing path, consumer
group management changes) belong in the 5.2 Subscription Profiles &
Tuning epic (R4), not the near-term roadmap.

### 5. Lint rule for cross-cluster event handling

A new `HANDLER_CREATES_FOREIGN_AGGREGATE` lint rule (WARNING level) will
detect event handlers that handle events from a different cluster than
the one they belong to (`part_of`). This is a structural smell that often
indicates a Process Manager would be more appropriate. The rule is
IR-based (no AST analysis needed) and fits into 3.5.4 (handler
completeness rules).

### 6. Connective pattern documentation

A new pattern page "Designing for Concurrent Event Processing" will tie
together the existing pattern docs (OCC, idempotent handlers, process
managers, error classification) with the four problem classes and a
worked example of the HubSpot scenario refactored three ways.

## Consequences

### Positive

- **No new infrastructure to maintain.** The framework stays lean.
  Concurrency safety comes from composing existing primitives (OCC, PM,
  idempotent patterns), not from new mechanisms.

- **DDD philosophy preserved.** Creation logic stays in the domain layer.
  Coordination logic stays in Process Managers. The framework guides
  developers toward correct patterns rather than providing database-level
  escape hatches.

- **Existing OCC gets stronger.** The atomic fix in 5.1 #793 closes the
  last real gap in version checking.

- **Lint rule catches the structural smell early.** Cross-cluster event
  handling without a PM is flagged before it causes production issues.

### Negative

- **Developers must understand the patterns.** There is no "just add
  `sequential_by` and it works" shortcut. The pattern doc must be
  excellent to bridge this gap.

- **`sequential_by` is deferred.** For high-throughput systems with many
  handlers on the same stream, the only current option for sequential
  processing is combining handlers or using a PM. Partition-key-based
  routing comes in R4.

- **No database-level upsert.** Developers who want `find_or_create`
  must implement it in their adapter layer outside the framework, or use
  the recommended DDD patterns instead.

## Alternatives Considered

### Full infrastructure suite (6 phases)

We evaluated a comprehensive approach: `concurrency_strategy` Meta
option, `find_or_create` repository primitive, partitioned streams
(`sequential_by`), `idempotent_by` on event handlers, 6 lint rules,
and scaffolding CLI. This was declined because most of the mechanisms
either already exist (OCC, command idempotency), conflict with DDD
philosophy (`find_or_create`), or are premature for the current roadmap
stage (partitioned streams).

### Framework-managed event deduplication

An idempotency store for events (similar to the existing command
`IdempotencyStore`) was considered. We decided against it because event
handler idempotency is a business-logic concern -- the right dedup
strategy varies by operation type, and the existing pattern docs already
provide comprehensive guidance.

### `CONCURRENT_ENTITY_HANDLERS` lint rule

A lint rule matching handlers by shared field names (e.g., both handlers
have `order_id`) was considered. We opted for the more precise
`HANDLER_CREATES_FOREIGN_AGGREGATE` rule instead, which detects
cross-cluster event handling via IR topology and has a significantly
lower false-positive rate.
