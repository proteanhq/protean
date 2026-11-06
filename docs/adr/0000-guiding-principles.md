# ADR-0000: Guiding Principles

**Status:** Accepted

**Date:** March 2026

This is not a decision record. It is a meta-document that captures the
principles governing all Protean architectural decisions. When you evaluate a
new proposal or resolve a conflict between two design goals, reason from these
principles.

---

## 1. Topology, not logic

The framework captures *what exists* and *how things connect*, never *what
happens inside*. Structural metadata (field names, handler targets, aggregate
clusters) is the framework's concern. Implementation logic (handler bodies,
invariant checks, factory methods) belongs to the developer.

**Example:** When `domain.init()` runs, the framework discovers that
`OrderCommandHandler` handles `PlaceOrder` and that `Order` raises
`OrderPlaced`. The framework does not inspect the handler's work on the command
data. It also does not inspect the conditions under which `Order` raises the
event. Invariant names and stages (`pre`/`post`) are registered as structural
metadata, but the invariant logic itself is opaque to the framework.

## 2. Declare, don't detect

Some information cannot be read from Python's type system or class structure.
For that information, you declare it explicitly through decorator options or
`Meta` attributes, and the framework never analyses source code or infers it
from naming conventions.

**Example:** The framework cannot infer whether an event crosses bounded
context boundaries. Rather than scanning handler bodies for external API calls,
we added the `published` option to `@domain.event(published=True)`. The
developer declares intent; the framework acts on it.

## 3. Explicit over automatic

Protean favors explicit registration and wiring over hidden auto-discovery.
Every domain element is registered through a decorator (`@domain.aggregate`,
`@domain.command_handler`) that makes the element's role and relationships
visible at the declaration site. Implicit behavior is acceptable only when the
default is obvious and the override is straightforward.

**Example:** Every command handler, event handler, and projector declares `part_of=SomeAggregate`
explicitly. The framework does not guess aggregate associations from module structure or naming.
Default repositories are provided automatically for every aggregate, but custom repositories
override them with an explicit `@domain.repository(part_of=Order)` declaration.

## 4. Compute freely, materialize deliberately, validate automatically

In-memory computation is cheap and should be unconstrained. When you persist
state (materializing), you act deliberately and the act has consequences. It
crosses a boundary. The framework validates automatically at every state
transition. You do not call validation at manual checkpoints.

**Example:** Aggregate invariants (`@invariant.pre`, `@invariant.post`) run on
every mutation automatically. The developer never calls `validate()`. The
framework guarantees that if an aggregate instance exists in memory, it
satisfies all its invariants. But to persist that aggregate, you make an
explicit repository call within a Unit of Work. That call makes the
materialization boundary visible.

## 5. DSL expressiveness must survive infrastructure migration

Protean's field DSL (`String(max_length=100)`, `HasMany("Comment")`,
`Status(transitions={...})`) must work identically regardless of the underlying
infrastructure. When you switch from PostgreSQL to Elasticsearch, or from Redis
Streams to an inline broker, you should not have to change domain model
declarations.

**Example:** The `FieldSpec` architecture translates `String(max_length=100)`
into Pydantic-compatible annotations during class creation. The FieldSpec
carries enough metadata for any adapter to map the field to its native storage
type (`Text` maps to a `TEXT` column in SQL and a `text` field in
Elasticsearch). You never write adapter-specific declarations. The domain model
is infrastructure-agnostic by construction.

## 6. Aggregate-centric, flow-aware

The primary organizational unit is the aggregate cluster, an aggregate and
everything that belongs to it (entities, value objects, commands, events,
handlers, repositories). Cross-cutting concerns (domain services, process
managers, subscribers) span more than one aggregate. The framework does not
force them into clusters and treats each one as an element in its own right.

**Example:** During `domain.init()`,
`ElementResolver.assign_aggregate_clusters()` groups entities, commands, and
events under their root aggregate by traversing `part_of` chains. But the
framework does not group process managers and domain services under any
aggregate. They coordinate across aggregate boundaries and belong to no single
cluster. This grouping follows DDD's distinction between aggregate internals
and cross-aggregate coordination.

## 7. Screaming architecture

Name folders, modules and classes after business concepts. Do not name them
after technical categories. When a developer opens the codebase, they should
see the domain concepts first. The framework's internal wiring should not be
what they see.

**Example:** Protean applications organize code by domain concept (`ordering/`, `inventory/`,
`shipping/`), not by technical layer (`models/`, `handlers/`, `repositories/`).
Within each domain module, the aggregate, its commands, events, and handlers
live together. The test directory mirrors the source structure
(`tests/aggregate/`, `tests/event/`, `tests/server/`) so navigation between
source and test is immediate.
