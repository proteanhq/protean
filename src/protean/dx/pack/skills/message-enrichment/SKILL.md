---
name: message-enrichment
description: Enrich Protean commands and events with cross-cutting metadata using command enrichers and event enrichers. Enrichers are domain-level functions that return a dict merged into a message's metadata.extensions, useful for tenant ids, request/correlation context, actor info, and audit data that should ride along with every command or event without polluting the payload. Use @domain.command_enricher for commands and @domain.event_enricher for events. A third kind, @domain.aggregate_enricher, stamps audit fields such as updated_by on an aggregate just before it is saved. Use when you need to attach context to messages, add metadata to commands or events, inject tenant/request/user info, enrich messages, build an audit trail, or when the user asks to "add a command enricher", "add an event enricher", "enrich commands/events", "attach metadata", or "inject context into messages".
license: Apache-2.0
compatibility: Requires Python 3.11+, protean framework
metadata:
  author: proteanhq
  version: "0.1"
  category: element
  diagnostic_codes:
    - USAGE_ENRICHER_NOT_CALLABLE
---

# Message Enrichment

Enrichers attach cross-cutting context to messages. A **command enricher** runs as a
command is processed; an **event enricher** runs as an aggregate raises an event. Each
returns a `dict` that is merged into the message's `metadata.extensions`, so the data
travels with the message (through serialization and the event store) without bloating
the payload.

An **aggregate enricher** is the third kind. It does not touch messages. It runs just
before an aggregate is saved and sets fields on the aggregate itself, such as
`updated_by` or `created_by`.

## Basic structure

```python
from protean import Domain
from protean.utils.globals import g

domain = Domain()

# Command enricher: receives the command, returns a dict
@domain.command_enricher
def add_request_context(command):
    return {"request_id": getattr(g, "request_id", None)}

# Event enricher: receives the event AND the aggregate, returns a dict
@domain.event_enricher
def add_tenant_context(event, aggregate):
    return {"tenant_id": getattr(g, "tenant_id", None)}

# Aggregate enricher: receives the aggregate, sets fields on it, returns nothing
@domain.aggregate_enricher
def stamp_updated_by(aggregate):
    if hasattr(aggregate, "updated_by"):
        aggregate.updated_by = g.get("current_user")
```

## Key rules

1. **Each kind has its own signature**: Command enricher: `def fn(command) -> dict`. Event enricher: `def fn(event, aggregate) -> dict` (it also gets the aggregate, so it can read aggregate state). Aggregate enricher: `def fn(aggregate) -> None`
2. **Register with the decorator**: `@domain.command_enricher` / `@domain.event_enricher` / `@domain.aggregate_enricher`. For reusable functions, use `domain.register_command_enricher(fn)` / `domain.register_event_enricher(fn)` / `domain.register_aggregate_enricher(fn)`
3. **Message enrichers return a dict (or `None`)**: The returned dict is merged into `metadata.extensions`. Returning `None` or `{}` is a no-op. An aggregate enricher sets fields on the aggregate instead, and its return value is ignored
4. **Enrichers are domain-level**: They are NOT `part_of` an aggregate; they run for every command (or every event) in the domain
5. **Run order is FIFO; later wins**: Enrichers run in registration order; a later enricher can overwrite a key set by an earlier one
6. **Keep them pure and fast**: A command or event enricher reads context (e.g. from `g`) and returns data. It must not change the message, load aggregates, or perform I/O. An aggregate enricher sets fields on the aggregate it receives, and it also must not load aggregates or perform I/O
7. **Errors abort the message**: If an enricher raises, the command is not processed / the event is not appended. Use safe access like `getattr(g, "key", None)`
8. **Timing**: Command enrichers run after command metadata is built, before handling; event enrichers run inside `aggregate.raise_()`, before the event is appended (and they also run for fact events); aggregate enrichers run whenever an aggregate is saved, on both create and update, including through `update()` and `QuerySet.update()`. They also run on the records the framework saves through repositories, such as outbox rows and the in-memory event store's message records, so an enricher skips any aggregate that does not declare the field it stamps
9. **Aggregate enrichers are for audit fields only**: Stamp fields like `updated_at`, `updated_by` and `created_by`. Do not enforce rules or raise events in them; that belongs in the aggregate's methods. They do not run for event-sourced aggregates, or for a save that passes `apply_hooks=False`

## Where the data lands

```python
# fragment
command._metadata.extensions   # after command enrichment
event._metadata.extensions     # after event enrichment
# Downstream, handlers/projectors read it via:
#   g.message_in_context.metadata.extensions
# An aggregate enricher writes to the aggregate's own fields
```

## Quick example: tenant + audit context

```python
from protean import Domain
from protean.utils.globals import g

domain = Domain()

@domain.command_enricher
def command_audit(command):
    return {
        "request_id": getattr(g, "request_id", None),
        "actor_id": getattr(g, "actor_id", None),
    }

@domain.event_enricher
def event_audit(event, aggregate):
    return {
        "tenant_id": getattr(g, "tenant_id", None),
        "aggregate_type": type(aggregate).__name__,
    }

@domain.aggregate
class Order:
    customer_id: String(required=True)
    created_by: String()
    updated_by: String()

@domain.aggregate_enricher
def stamp_audit(aggregate):
    if not hasattr(aggregate, "updated_by"):  # a framework record, such as an outbox row
        return
    user = g.get("current_user")
    aggregate.updated_by = user
    if aggregate.created_by is None:  # set once, on create
        aggregate.created_by = user

domain.init(traverse=False)

# Put the acting user on the context so the aggregate enricher can read it
with domain.domain_context(current_user="alice"):
    order = Order(customer_id="c-1")
    domain.repository_for(Order).add(order)
    assert order.created_by == "alice"
```

## Common mistakes

### Putting business data in extensions

Extensions are for cross-cutting metadata (tenant, request, actor), not domain
payload. Domain data belongs in the command/event fields.

### Registering a non-callable enricher

```python
# fragment
domain.register_event_enricher(some_dict)  # Wrong! Not callable
```

Registering anything that is not callable raises `IncorrectUsageError` with code
`USAGE_ENRICHER_NOT_CALLABLE`.

## Detailed references

- [Anti-patterns](references/anti-patterns.md): Common mistakes and how to avoid them

### Complete examples

- [Command Enricher](assets/command_enricher_basic.py): Enrich commands with request context
- [Event Enricher](assets/event_enricher_basic.py): Enrich events with tenant + aggregate context

### Related skills

- `command` / `command-handler`: Commands that enrichers annotate
- `event` / `event-handler`: Events that enrichers annotate
- `aggregate`: Event enrichers receive the aggregate raising the event

## Verify your work

- [Verify with check](../../references/verify-with-check.md): run `check` and resolve what it reports
