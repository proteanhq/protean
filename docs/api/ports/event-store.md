# BaseEventStore

Event store interface for event-sourced persistence. All event store adapters
(Memory, MessageDB, etc.) implement this contract.

See [Event Store Adapters](../../reference/adapters/eventstore/index.md) for
concrete adapter configuration.

::: protean.port.event_store.BaseEventStore
    options:
      show_root_heading: false

---

## EventStorePort

The `typing.Protocol` every event store implements. `BaseEventStore`
subclasses it, and the `EventStore` service builds the event store's reads,
writes, aggregate loading and snapshots on these members.

::: protean.port.event_store.EventStorePort
    options:
      show_root_heading: false

---

## EventStore

The service that `domain.event_store` returns. It holds the domain's adapter
and provides reads, writes, aggregate loading, snapshots, causation tracing and
the integrity check.

::: protean.infra.event_store.EventStore
    options:
      show_root_heading: false

---

## RawMessage

The row an event store returns from a read.

::: protean.port.event_store.RawMessage
    options:
      show_root_heading: false

---

## EventStoreHealth

What `health()` reports: whether the store answered, and its connection pool
counts when the store has a pool.

::: protean.port.event_store.EventStoreHealth
    options:
      show_root_heading: false

---

## EventStoreCapabilities

The guarantees an event store declares on its `capabilities` property.

::: protean.port.event_store.EventStoreCapabilities
    options:
      show_root_heading: false

---

## CausationNode

Tree node used by `build_causation_tree()` to represent the causation
hierarchy of messages sharing a `correlation_id`.

::: protean.infra.causation.CausationNode
    options:
      show_root_heading: false

---

## IntegrityReport

The result of `verify()`, and the `data` payload of
`protean eventstore verify --json`.

::: protean.infra.integrity.IntegrityReport
    options:
      show_root_heading: false

---

## IntegrityViolation

One broken invariant that `verify()` found.

::: protean.infra.integrity.IntegrityViolation
    options:
      show_root_heading: false

---

## ViolationKind

The kinds of `IntegrityViolation`. Each value is the string that
`--json` writes.

::: protean.infra.integrity.ViolationKind
    options:
      show_root_heading: false
