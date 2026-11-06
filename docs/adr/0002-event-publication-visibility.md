# Decide how events are published and made visible across bounded context boundaries (ADR-0002)

**Status:** Proposed

**Date:** March 2026

## Context

Domain events in Protean are raised by aggregates and processed by event
handlers within the same bounded context. But some events need to cross bounded
context boundaries. For example, the notification context or the analytics
context may need to consume an `OrderShipped` event from the ordering context.

The framework needs to let developers declare which events are part of the
domain's "published language". The published language is the subset of events
that external consumers can depend on. This distinction matters because
published events have stricter compatibility requirements (changing them may
break external consumers) and need routing through external brokers in addition
to internal handlers. The IR's `contracts` section should also catalog them for
documentation and contract validation.

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

The term "published" comes from Eric Evans' Published Language pattern in the
DDD blue book. A published event is one that the bounded context commits to
maintaining as a stable contract for external consumers. The default is
`published=False`. Events are internal unless explicitly declared otherwise.

In the IR, published events appear in two places. First, inline on the event
element within its cluster (`"published": true`), where it's immediately
available during element-by-element processing. Second, published events appear
in the top-level `contracts` section. This section is a derived summary of all
published events, for consumers that need only the event contracts (API
gateways, documentation generators, schema registries).

The `contracts` section is derived. Both representations come from the same
developer declaration. Because the IR carries both representations, consumers
can use either one: they can scan every cluster for published events, or they
can read the separate contracts section.

Only events can be published. Commands are always internal to the bounded
context. Subscribers receive external happenings as messages at the boundary
and translate them into internal commands, acting as an anti-corruption layer.
This is a DDD principle: commands are imperative ("do this"), events are
factual ("this happened"). External systems react to facts, not imperatives.

## Consequences

The `published` flag gives developers a declarative way to mark events as
external contracts. No static analysis of handler bodies or broker
configurations is needed (see ADR-0000, principle 2).

The IR's `contracts` section enables contract validation tooling (Phase 4). Diffing two IR
versions reveals which published events changed shape, allowing CI pipelines to flag
breaking changes before deployment.

The dual representation (inline + contracts section) means some information is present in
two places. This is intentional. The inline flag serves element-level
processing, the contracts section serves contract-level queries. Both are
derived from the same source, so consistency is guaranteed by the builder.

The limitation is that `published` is a boolean. An event is either published
or it isn't. We considered using `visibility` with string values (`"internal"`,
`"published"`, `"deprecated"`) for future extensibility. With the `visibility`
approach, developers could control visibility more finely (e.g., mark an event
as visible to specific consumers or as deprecated-but-still-supported).
However, the simpler boolean is enough for the immediate need. Under the
compatibility contract, Protean can add a `visibility` attribute alongside
`published` in a future minor version if developers need richer semantics.

This ADR remains in **Proposed** status because the Protean maintainers are
still evaluating the exact mechanism for routing published events to external
brokers. The `published` declaration exists in the framework, but the
maintainers are still refining the server's dispatch logic for routing
published events to external brokers.

## Alternatives Considered

**`visibility` with string values** (`"internal"`, `"published"`,
`"deprecated"`) offers more expressiveness. It also forces vocabulary decisions
(what other visibility levels might exist?) and adds complexity for the common
case (most events are internal, some are published). We may revisit this if the
boolean proves insufficient.

We considered **per-command event causality** (`produces` declarations on
commands listing which events they may raise) for richer contract
documentation. We rejected it because handler logic is conditional. A
`PlaceOrder` command may raise `OrderPlaced` or `OrderRejected` depending on
business rules. Static declarations of this kind drift from reality as the
domain evolves. The aggregate-to-events mapping (via `part_of`) provides the
coarser but always-accurate relationship.
