---
name: message-enrichment
description: Enrich Protean commands and events with cross-cutting metadata using command enrichers and event enrichers. Enrichers are domain-level functions that return a dict merged into a message's metadata.extensions - useful for tenant ids, request/correlation context, actor info, and audit data that should ride along with every command or event without polluting the payload. Use @domain.command_enricher for commands and @domain.event_enricher for events. Use when you need to attach context to messages, add metadata to commands or events, inject tenant/request/user info, enrich messages, build an audit trail, or when the user asks to "add a command enricher", "add an event enricher", "enrich commands/events", "attach metadata", or "inject context into messages".
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
```

## Key rules

1. **Two kinds, two signatures** - Command enricher: `def fn(command) -> dict`. Event enricher: `def fn(event, aggregate) -> dict` (it also gets the aggregate, so it can read aggregate state)
2. **Register with the decorator** - `@domain.command_enricher` / `@domain.event_enricher`. For reusable functions, use `domain.register_command_enricher(fn)` / `domain.register_event_enricher(fn)`
3. **Return a dict (or `None`)** - The returned dict is merged into `metadata.extensions`. Returning `None` or `{}` is a no-op
4. **Enrichers are domain-level** - They are NOT `part_of` an aggregate; they run for every command (or every event) in the domain
5. **Run order is FIFO; later wins** - Enrichers run in registration order; a later enricher can overwrite a key set by an earlier one
6. **Keep them pure and fast** - Read context (e.g. from `g`), return data. Do not mutate the message, load aggregates, or perform I/O
7. **Errors abort the message** - If an enricher raises, the command is not processed / the event is not appended. Use safe access like `getattr(g, "key", None)`
8. **Timing** - Command enrichers run after command metadata is built, before handling; event enrichers run inside `aggregate.raise_()`, before the event is appended (and they also run for fact events)

## Where the data lands

```python
command._metadata.extensions   # after command enrichment
event._metadata.extensions     # after event enrichment
# Downstream, handlers/projectors read it via:
#   g.message_in_context.metadata.extensions
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
```

## Common mistakes

### Wrong signature for an event enricher

```python
@domain.event_enricher
def add_ctx(event):  # Wrong! Event enrichers receive (event, aggregate)
    return {...}
```

Instead: `def add_ctx(event, aggregate): ...`

### Mutating the message instead of returning a dict

```python
@domain.command_enricher
def add_ctx(command):
    command._metadata.extensions["x"] = 1  # Wrong! Don't mutate
```

Instead: return a dict; Protean merges it into extensions.

### Unsafe context access

```python
@domain.command_enricher
def add_ctx(command):
    return {"request_id": g.request_id}  # Raises if unset -> aborts the command
```

Instead: `getattr(g, "request_id", None)`.

### Putting business data in extensions

Extensions are for cross-cutting metadata (tenant, request, actor), not domain
payload. Domain data belongs in the command/event fields.

## Detailed references

- [Anti-patterns](references/anti-patterns.md) - Common mistakes and how to avoid them

### Complete examples

- [Command Enricher](assets/command_enricher_basic.py) - Enrich commands with request context
- [Event Enricher](assets/event_enricher_basic.py) - Enrich events with tenant + aggregate context

### Related skills

- `command` / `command-handler` - Commands that enrichers annotate
- `event` / `event-handler` - Events that enrichers annotate
- `aggregate` - Event enrichers receive the aggregate raising the event

## Verify your work

- [Verify with check](../../references/verify-with-check.md): run `check` and resolve what it reports
