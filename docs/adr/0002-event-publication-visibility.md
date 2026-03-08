# ADR-0002: Event Publication and Visibility for Cross-BC Boundaries

**Status:** Proposed

**Date:** March 2026

## Context

Domain events in Protean are raised by aggregates and processed by event handlers within
the same bounded context. But some events need to cross bounded context boundaries — an
`OrderShipped` event in the ordering context may need to be consumed by the notification
context or the analytics context.

The framework needs a way for developers to declare which events are part of the domain's
"published language" — the subset of events that external consumers can depend on. This
distinction matters for several reasons: published events have stricter compatibility
requirements (changing them may break external consumers), they need to be routed through
external brokers (not just internal handlers), and the IR's `contracts` section should
catalog them for documentation and contract validation.

The question is what terminology and mechanism to use for this declaration.

## Decision

We will use the `published` option on the event decorator to mark events that cross bounded
context boundaries:

```python
@domain.event(part_of=Order, published=True)
class OrderShipped(BaseEvent):
    order_id: Identifier(identifier=True)
    shipped_at: DateTime()
```

The term "published" is grounded in Eric Evans' Published Language pattern from the DDD
blue book. A published event is one that the bounded context commits to maintaining as a
stable contract for external consumers. The default is `published=False` — events are
internal unless explicitly declared otherwise.

In the IR, published events appear in two places. First, inline on the event element within
its cluster (`"published": true`), where it's immediately available during element-by-element
processing. Second, in the top-level `contracts` section, which provides a derived summary
of all published events for consumers that only need the contract surface (API gateways,
documentation generators, schema registries).

The `contracts` section is derived — both representations come from the same developer
declaration. This dual approach avoids forcing consumers to choose between scanning every
cluster for published events or reading a separate contracts section.

Only events can be published. Commands are always internal to the bounded context. External
happenings arrive as messages at the boundary via subscribers (acting as an anti-corruption
layer) and get translated into internal commands. This is a DDD principle: commands are
imperative ("do this"), events are factual ("this happened"). External systems react to
facts, not imperatives.

## Consequences

The `published` flag provides a clear, declarative mechanism for marking events as external
contracts. No static analysis of handler bodies or broker configurations is needed (see
ADR-0000, principle 2).

The IR's `contracts` section enables contract validation tooling (Phase 4). Diffing two IR
versions reveals which published events changed shape, allowing CI pipelines to flag
breaking changes before deployment.

The dual representation (inline + contracts section) means some information is present in
two places. This is intentional — the inline flag serves element-level processing, the
contracts section serves contract-level queries. Both are derived from the same source, so
consistency is guaranteed by the builder.

The limitation is that `published` is a boolean — an event is either published or it isn't.
We considered using `visibility` with string values (`"internal"`, `"published"`,
`"deprecated"`) for future extensibility. The `visibility` approach would allow finer-grained
control (e.g., marking an event as visible to specific consumers or deprecated-but-still-
supported). However, the simpler boolean covers the immediate need, and the compatibility
contract allows adding a `visibility` attribute alongside `published` in a
future minor version if richer semantics are needed.

This ADR remains in **Proposed** status because the exact mechanism for external broker
routing of published events is still under evaluation. The `published` declaration exists
in the framework, but the server's dispatch logic for routing published events to external
brokers is being refined.

## Alternatives Considered

**`visibility` with string values** (`"internal"`, `"published"`, `"deprecated"`) offers
more expressiveness but introduces vocabulary decisions (what other visibility levels might
exist?) and adds complexity for the common case (most events are internal, some are
published). We may revisit this if the boolean proves insufficient.

**Per-command event causality** (`produces` declarations on commands listing which events
they may raise) was considered for richer contract documentation. We rejected it because
handler logic is conditional — a `PlaceOrder` command may raise `OrderPlaced` or
`OrderRejected` depending on business rules. Static declarations of this kind drift from
reality as the domain evolves. The aggregate-to-events mapping (via `part_of`) provides
the coarser but always-accurate relationship.
