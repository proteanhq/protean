# ADR-0009: Concurrent Event Processing Strategy

| Field | Value |
|-------|-------|
| **Status** | Accepted |
| **Date** | 2026-03-24 |
| **Author** | Subhash Bhushan |

## Context

A production incident in a HubSpot integration exposed a class of
concurrency bugs in event-driven systems. Two webhooks, Client Creation (CC)
and Client-Contact Association Change (CCA), fired in rapid succession. Two
workers picked up these events concurrently. The CC handler began creating a
Client aggregate. Simultaneously, the CCA handler looked for the Client, didn't
find it yet (CC hadn't committed), and created its own copy. Result: duplicate
Client records.

After the duplicate Client records, we analysed in depth how Protean processes
events concurrently. We found four problem classes:

1. **Concurrent entity creation**: Multiple events trigger "find or
   create" logic for the same aggregate
2. **Concurrent aggregate mutation**: Multiple events modify the same
   aggregate simultaneously
3. **Causal dependency violation**: Event B depends on side effects of
   event A, but B executes before A's effects are visible
4. **Duplicate processing**: The same event is delivered twice due to
   at-least-once delivery semantics

We surveyed Axon (Java), Eventuous (.NET), Marten (.NET), and Wolverine (.NET).
The frameworks among them that handle concurrency well share three traits. Each
one serializes changes per aggregate, uses OCC as a fallback check for
conflicts, and asks the developer to choose the concurrency model explicitly.

We had to decide whether Protean needed new infrastructure, such as partitioned
streams, handler-level idempotency stores, repository upsert primitives, or new
aggregate Meta options. The other option was that Protean's existing elements
already solve these problem classes.

## Decision

**Protean already provides the building blocks for safe concurrent event
processing. The framework will not add new concurrency infrastructure in the
near term. Instead, the framework will fix the atomic race condition in
existing OCC and add a lint rule for a common structural smell: an event
handler that handles events from another cluster. It will also publish a
pattern page that connects the existing concurrency patterns.**

Specifically:

### 1. OCC is always-on, not opt-in

Every aggregate already has a `_version` field (auto-managed,
starts at -1). The DAO's `_validate_and_update_version()` runs on every
save and raises `ExpectedVersionError` on mismatch. The `@handle`
decorator retries with exponential backoff (3 retries, 50ms-1s,
configurable via `[server.version_retry]`).

We will **not** add a `concurrency_strategy = "optimistic"` Meta option. OCC is
a correctness mechanism, not a configuration choice. Adding an opt-in would
imply that running without version checking is a valid option. It is not.

We will fix the existing atomic race condition (SELECT-compare-UPDATE instead
of conditional UPDATE) in release 5.1 (issue #793). This is a bug fix in
existing infrastructure, not new infrastructure.

### 2. No `find_or_create` repository primitive

`find_or_create` pushes creation logic to the database level, bypassing
aggregate constructors, invariant checking, and event raising. This
conflicts with Protean's design philosophy: "Validation lives in the
domain layer (invariants), not the database layer."

The DDD-correct solutions for creation races are:

- **Process Manager**: Coordinates the flow when events have causal
  dependencies (CC must complete before CCA can act)
- **Combine into a single handler**: If both events target the same
  aggregate, a single handler serializes processing naturally
- **Add unique constraints and retry**: The database rejects duplicates through
  unique constraints. The `ExpectedVersionError` retry then recovers from the
  transient conflict.

### 3. No framework-level event handler idempotency

We considered adding `idempotent_by` on event handlers with a
framework-managed idempotency store, but decided against it because:

- Idempotency is inherently a business-logic concern. The "right" deduplication
  strategy depends on the operation (set-based, dedup-tracked, upsert).
- Protean already has comprehensive pattern documentation for
  idempotent event handlers (600+ lines covering three strategies)
- Command idempotency via `IdempotencyStore` is already built for the
  submission boundary where framework-level dedup makes sense

### 4. `sequential_by` deferred to R4

> **Superseded by the partition-per-key ADR (ADR-0028).** This deferral no
longer applies. In the 5.2 Subscription Profiles & Tuning epic, we accepted the
partition-per-key design in its own ADR (ADR-0028). That ADR sets the stream
scheme, key handling, single-active-consumer enforcement (ownership with a
fencing token), and halt-on-poison behavior. The rest of this ADR (ADR-0009)
still applies. Only this section's deferral is superseded.

Within-handler sequential processing by partition key (`sequential_by`) is a
legitimate feature. The simpler solutions (PM, combine handlers, OCC retry)
solve the vast majority of cases. The infrastructure changes required
(partitioned streams, modified event publishing path, consumer group management
changes) belong in the 5.2 Subscription Profiles & Tuning epic (R4), not the
near-term roadmap.

### 5. Lint rule for cross-cluster event handling

A new `HANDLER_CREATES_FOREIGN_AGGREGATE` lint rule (WARNING level) will detect
an event handler that handles events from a different cluster. A handler's own
cluster is the one its `part_of` names. Such a handler is a structural smell.
It often means a Process Manager would be more appropriate. The rule reads the
IR and needs no AST analysis. It belongs with the handler completeness rules
(3.5.4).

### 6. Connective pattern documentation

A new pattern page, "Designing for Concurrent Event Processing", will link the
existing pattern docs on OCC, idempotent handlers, process managers, and error
classification to the four problem classes listed under Context. The page will
also show the HubSpot duplicate-Client incident refactored three ways as a
worked example.

## Consequences

### Positive

- **No new infrastructure to maintain**: The framework adds no new components.
  Concurrency safety comes from composing existing primitives (OCC, PM,
  idempotent patterns), not from new mechanisms.

- **DDD philosophy preserved**: Creation logic stays in the domain layer.
  Coordination logic stays in Process Managers. The framework documents the
  correct patterns for developers. It offers no database-level operations that
  bypass the domain layer.

- **Existing OCC becomes atomic**: The fix in release 5.1 (issue #793) removes
  the last real race condition in version checking.

- **The linter reports the structural smell early**: The linter warns about
  cross-cluster event handling without a PM before that code causes production
  issues.

### Negative

- **Developers must understand the patterns**: Protean offers no single option,
  such as `sequential_by`, that makes concurrent processing safe without them.
  We must write the new concurrency pattern page well enough that developers
  can learn the patterns from it.

- **`sequential_by` is deferred**: For high-throughput systems with many
  handlers on the same stream, the only current option for sequential
  processing is combining handlers or using a PM. Partition-key-based routing
  comes in the Subscription Profiles & Tuning epic (R4).

- **Protean offers no database-level upsert**: A developer who wants
  `find_or_create` must implement it in their own adapter layer, outside the
  framework. The other choice is to use the recommended DDD patterns instead.

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

We considered an idempotency store for events (similar to the existing command
`IdempotencyStore`). We decided against it because event handler idempotency is
a business-logic concern, the right dedup strategy varies by operation type,
and the existing pattern docs already provide comprehensive guidance.

### `CONCURRENT_ENTITY_HANDLERS` lint rule

We considered a lint rule that matches handlers by shared field names (e.g.,
both handlers have `order_id`). We opted for the more precise
`HANDLER_CREATES_FOREIGN_AGGREGATE` rule instead, which detects cross-cluster
event handling via IR topology and has a significantly lower false-positive
rate.
