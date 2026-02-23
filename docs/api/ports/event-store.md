# BaseEventStore

Event store interface for event-sourced persistence. All event store adapters
(Memory, MessageDB, etc.) implement this contract.

See [Event Store Adapters](../../reference/adapters/eventstore/index.md) for
concrete adapter configuration.

::: protean.port.event_store.BaseEventStore
    options:
      show_root_heading: false

---

## CausationNode

Tree node used by `build_causation_tree()` to represent the causation
hierarchy of messages sharing a `correlation_id`.

::: protean.port.event_store.CausationNode
    options:
      show_root_heading: false
