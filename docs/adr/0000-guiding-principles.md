# ADR-0000: Guiding Principles

**Status:** Accepted

**Date:** March 2026

This is not a decision record. It is a meta-document that captures the principles governing
all Protean architectural decisions. When evaluating a new proposal or resolving a design
tension, these principles provide the framework for reasoning.

---

## 1. Topology, not logic

The framework captures *what exists* and *how things connect* — never *what happens inside*.
Structural metadata (field names, handler targets, aggregate clusters) is the framework's
concern. Implementation logic (handler bodies, invariant checks, factory methods) belongs
to the developer.

**Example:** When `domain.init()` runs, the framework discovers that `OrderCommandHandler`
handles `PlaceOrder` and that `Order` raises `OrderPlaced`. It does not inspect what the
handler does with the command data or what conditions cause the event to be raised. Invariant
names and stages (`pre`/`post`) are registered as structural metadata, but the invariant
logic itself is opaque to the framework.

## 2. Declare, don't detect

When the framework needs information that isn't naturally introspectable from Python's type
system or class structure, the answer is explicit developer declaration via decorator options
or `Meta` attributes — never static analysis of source code, never inference from naming
conventions.

**Example:** Whether an event crosses bounded context boundaries is not something the framework
can infer. Rather than scanning handler bodies for external API calls, we added the `published`
option to `@domain.event(published=True)`. The developer declares intent; the framework acts
on it.

## 3. Explicit over automatic

Protean favors explicit registration and wiring over magic auto-discovery. Every domain element
is registered through a decorator (`@domain.aggregate`, `@domain.command_handler`) that makes
the element's role and relationships visible at the declaration site. Implicit behavior is
acceptable only when the default is obvious and the override is straightforward.

**Example:** Every command handler, event handler, and projector declares `part_of=SomeAggregate`
explicitly. The framework does not guess aggregate associations from module structure or naming.
Default repositories are provided automatically for every aggregate, but custom repositories
override them with an explicit `@domain.repository(part_of=Order)` declaration.

## 4. Compute freely, materialize deliberately, validate automatically

In-memory computation is cheap and should be unconstrained. Persisting state (materializing)
is a deliberate act with consequences — it crosses a boundary. Validation happens automatically
at every state transition, not at manual checkpoints.

**Example:** Aggregate invariants (`@invariant.pre`, `@invariant.post`) run on every mutation
automatically. The developer never calls `validate()` — the framework guarantees that if an
aggregate instance exists in memory, it satisfies all its invariants. But persisting that
aggregate requires an explicit repository call within a Unit of Work, making the materialization
boundary visible.

## 5. DSL expressiveness must survive infrastructure migration

Protean's field DSL (`String(max_length=100)`, `HasMany("Comment")`, `Status(transitions={...})`)
must work identically regardless of the underlying infrastructure. Switching from PostgreSQL to
Elasticsearch, or from Redis Streams to an inline broker, should not require changing domain
model declarations.

**Example:** The `FieldSpec` architecture translates `String(max_length=100)` into
Pydantic-compatible annotations during class creation. The FieldSpec carries enough metadata
for any adapter to map the field to its native storage type — `Text` maps to a `TEXT` column
in SQL and a `text` field in Elasticsearch — but the developer never writes adapter-specific
declarations. The domain model is infrastructure-agnostic by construction.

## 6. Aggregate-centric, flow-aware

The primary organizational unit is the aggregate cluster — an aggregate and everything that
belongs to it (entities, value objects, commands, events, handlers, repositories). Cross-cutting
concerns (domain services, process managers, subscribers) are not forced into clusters but get
explicit treatment where their multi-aggregate nature is first-class.

**Example:** During `domain.init()`, `ElementResolver.assign_aggregate_clusters()` groups
entities, commands, and events under their root aggregate by traversing `part_of` chains.
But process managers and domain services stand apart — they coordinate across aggregate
boundaries and belong to no single cluster. This mirrors DDD's distinction between aggregate
internals and cross-aggregate coordination.

## 7. Screaming architecture

The folder structure, module names, and class names should communicate business concepts,
not technical categories. A developer opening the codebase should immediately see the domain,
not the framework plumbing.

**Example:** Protean applications organize code by domain concept (`ordering/`, `inventory/`,
`shipping/`), not by technical layer (`models/`, `handlers/`, `repositories/`). Within each
domain module, the aggregate, its commands, events, and handlers live together. The test
directory mirrors the source structure — `tests/aggregate/`, `tests/event/`, `tests/server/`
— so navigation between source and test is immediate.
