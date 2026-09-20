# Catch-All ($any) Handler

The `@handle("$any")` decorator creates a catch-all handler that processes any event on the subscribed stream, regardless of event type.

## Overview

The `$any` handler is a fallback mechanism. It is invoked for events that do not have a specific `@handle(EventClass)` method. If a specific handler exists for an event type, that handler takes precedence.

Common use cases:
- **Audit logging**: Record every event for compliance
- **Metrics collection**: Count or measure all events
- **Event forwarding**: Relay events to external systems
- **Debugging**: Log all events during development

## Code

The complete implementation is in [assets/event_handler_any_event.py](../assets/event_handler_any_event.py).

Key highlights:
- `@handle("$any")` catches all events on the stream
- Only ONE `$any` handler method per event handler class (if multiple are defined, the last one wins)
- Specific `@handle(EventClass)` methods take precedence over `$any`

## How It Works

### Handler Registration

```python
@domain.event_handler(part_of=AuditLog, stream_category=Task.meta_.stream_category)
class TaskAuditor:
    @handle("$any")
    def on_any_task_event(self, event):
        audit_entry = AuditLog(
            event_type=event.__class__.__name__,
            details=f"Event received: {event.__class__.__name__}",
        )
        domain.repository_for(AuditLog).add(audit_entry)
```

The `$any` handler is registered in the `_handlers` dict under the key `"$any"` instead of an event type string.

### Fallback Behavior

When `_handle()` is called on the handler:

1. It looks for specific handlers matching the event's type
2. If none found, it falls back to the `$any` handler
3. If no `$any` handler exists either, no processing occurs

### Only One $any Per Handler

If you define multiple `@handle("$any")` methods, only the last one is used:

```python
class MyHandler:
    @handle("$any")
    def handler1(self, event):  # Will be replaced
        pass

    @handle("$any")
    def handler2(self, event):  # This one wins
        pass
```

## Combining $any with Specific Handlers

You can mix `$any` with specific handlers. Specific handlers take precedence:

```python
@domain.event_handler(part_of=AuditLog, stream_category=Task.meta_.stream_category)
class TaskAuditor:
    @handle(TaskCreated)
    def on_task_created(self, event: TaskCreated):
        # This handles TaskCreated events specifically
        ...

    @handle("$any")
    def on_any_event(self, event):
        # This handles all OTHER events (not TaskCreated)
        ...
```

## Related

- [Same-Aggregate](./same-aggregate.md) - Basic event handler pattern
- [Cross-Aggregate](./cross-aggregate.md) - Cross-aggregate coordination
- [Anti-patterns](./anti-patterns.md) - Common mistakes
