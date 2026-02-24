# Chapter 14: Connecting to the Outside World

Fidelis integrates with "PayFlow," an external payment gateway that
sends webhook notifications when payments are processed. These external
messages are raw JSON payloads — not typed domain events.

In this chapter we will build a **subscriber** that acts as an
anti-corruption layer, and add **enrichers** to attach cross-cutting
metadata to every message flowing through the system.

## Subscribers: The Anti-Corruption Layer

A subscriber consumes messages from an external system and translates
them into domain operations:

```python
--8<-- "guides/getting-started/es-tutorial/ch14.py:subscriber"
```

Key differences from event handlers:

| | Event Handlers | Subscribers |
|---|---------------|------------|
| **Input** | Typed domain events | Raw `dict` payloads |
| **Source** | Internal event streams | External broker streams |
| **Interface** | `@handle(EventType)` methods | `__call__(self, payload)` |
| **Purpose** | React to domain events | Translate external messages |

The subscriber is the **translation layer**: it converts external
concepts (PayFlow webhook schema) into domain concepts (Fidelis
commands). The domain never sees the raw webhook format.

## Error Handling

Subscribers can override `handle_error` for custom error handling:

```python
@classmethod
def handle_error(cls, exc: Exception, message: dict) -> None:
    print(f"[PayFlow Error] Failed to process webhook: {exc}")
```

This is called when `__call__` raises an exception, giving you a chance
to log, alert, or transform the error before it propagates to the
subscription's retry/DLQ mechanism.

## Message Enrichment

Event and command enrichers add metadata that does not belong in the
event payload itself — infrastructure concerns like tenant IDs, request
IDs, and user context:

```python
--8<-- "guides/getting-started/es-tutorial/ch14.py:event_enricher"
```

```python
--8<-- "guides/getting-started/es-tutorial/ch14.py:command_enricher"
```

Key concepts:

- **Event enrichers** receive `(event, aggregate)` and return a `dict`
  of metadata extensions.
- **Command enrichers** receive `(command,)` and return a `dict`.
- Enrichment data appears in **`metadata.extensions`**, not in the event
  fields. This keeps domain events clean.
- Multiple enrichers execute in **FIFO order**, with results merged.
- Enrichers run automatically — no code changes needed in aggregates
  or handlers.

## When to Use Enrichers

Enrichers are for **cross-cutting concerns** that apply to all messages:

- Tenant ID (multi-tenancy)
- User ID / actor context (audit trails)
- Request ID (request tracing)
- Feature flags or experiment IDs

Do **not** put domain-specific data in enrichers. If a field is part
of the business event (like `amount` or `reference`), it belongs in
the event definition.

## Accessing Enrichment Data

In event handlers and projectors, access enrichment data through the
event's metadata:

```python
@handle(DepositMade)
def on_deposit(self, event: DepositMade):
    tenant_id = event._metadata.extensions.get("tenant_id")
    request_id = event._metadata.extensions.get("request_id")
```

## What We Built

- A **PayFlowWebhookSubscriber** that translates external webhooks
  into domain commands.
- **`@domain.event_enricher`** for attaching metadata to events.
- **`@domain.command_enricher`** for attaching metadata to commands.
- The **anti-corruption layer** pattern for external integrations.
- **`metadata.extensions`** for cross-cutting metadata.

Part III is complete. We have evolved the system with schema changes
(upcasting), performance optimization (snapshots), historical queries
(temporal), and external integration (subscribers and enrichers). In
Part IV, we tackle production operations — the daily reality of running
an event-sourced system.

## Full Source

```python
--8<-- "guides/getting-started/es-tutorial/ch14.py:full"
```

## Next

[Chapter 15: Fact Events and the Reporting Pipeline →](15-fact-events.md)
