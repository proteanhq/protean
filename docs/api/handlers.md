# Handlers

Command handlers, event handlers, and query handlers process messages. Command
and event handlers are associated with aggregates. They use the `@handle`
decorator. Query handlers are associated with projections. They use the `@read`
decorator.

**Read the guides:** [Command
Handlers](../guides/change-state/command-handlers.md) · [Event
Handlers](../guides/consume-state/event-handlers.md) · [Query
Handlers](../guides/consume-state/query-handlers.md)

---

::: protean.core.command_handler.BaseCommandHandler
    options:
      inherited_members: false

---

::: protean.core.event_handler.BaseEventHandler
    options:
      inherited_members: false

---

::: protean.core.query_handler.BaseQueryHandler
    options:
      inherited_members: false
