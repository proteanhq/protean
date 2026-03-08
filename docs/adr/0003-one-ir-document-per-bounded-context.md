# ADR-0003: One IR Document per Bounded Context

**Status:** Accepted

**Date:** March 2026

## Context

Protean's `Domain` class is the composition root — it holds all registered elements,
resolves references, assigns aggregate clusters, and wires handlers. A natural question
arises: what is the scope of a single Internal Representation (IR) document? Does it
represent a module, an aggregate, a bounded context, or an entire system?

In DDD, a bounded context is the boundary within which a particular domain model applies.
Within a bounded context, terms have precise meanings and models are internally consistent.
Across bounded contexts, the same term may mean different things (a "Customer" in billing
vs. shipping).

Some developers, especially early in a project, may use a single `Domain` instance for what
are logically separate bounded contexts. Others may split too early, creating artificial
boundaries. The IR needs a clear scope that matches how Protean actually works.

## Decision

We will produce one IR document per `Domain` instance, and one `Domain` instance represents
one bounded context. The equation is: **one Domain = one BC = one IR document.**

Multiple aggregates within one `Domain` are clusters within a single bounded context —
`Order` and `Payment` aggregates in the same domain are not separate BCs. This is normal
DDD. The IR captures their relationships (shared events, cross-aggregate handlers) because
they exist within the same consistency boundary.

Multi-bounded-context visualization (context maps, inter-BC event flows) requires aggregating
multiple IR documents from separate `Domain` instances. Each IR captures one deployment
domain. Cross-BC features are explicitly deferred to Phase 6 (context maps) and Phase 14
(multi-repo) of the IR roadmap.

## Consequences

The IR is self-contained. Every FQN reference within the document resolves to an element
within the same document. There are no dangling cross-document references to manage, no
import mechanism, no dependency resolution between IR files.

Tooling that needs a system-wide view (architecture diagrams spanning multiple services,
cross-BC event flow visualization) must aggregate multiple IR documents. This is a deliberate
separation — each IR is a complete, valid unit. Aggregation is a tool concern, not a schema
concern.

The known limitation is that the IR cannot represent sub-context boundaries within a single
`Domain`. If a developer packs two logically distinct bounded contexts into one `Domain`
instance, the IR treats them as one. Phase 5 linting may detect this pattern (aggregate
clusters with no event flow between them) and emit an informational diagnostic, but the
IR itself will not add sub-context declarations unless Protean introduces explicit bounded
context partitioning within a `Domain`.

This also means that Protean does not support multi-BC abstractions at the framework level.
The framework is deliberately opinionated: if you need separate bounded contexts, use
separate `Domain` instances. This avoids premature sub-context abstraction and keeps the
`Domain` class focused on a single responsibility.
