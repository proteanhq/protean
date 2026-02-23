# Handlers

Command handlers and event handlers process messages asynchronously. They
are always associated with an aggregate and use the `@handle` decorator to
map specific message types to methods.

**Guides:**
[Command Handlers](../guides/change-state/command-handlers.md) ·
[Event Handlers](../guides/consume-state/event-handlers.md)

---

::: protean.core.command_handler.BaseCommandHandler
    options:
      inherited_members: false

---

::: protean.core.event_handler.BaseEventHandler
    options:
      inherited_members: false
