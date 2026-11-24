# Catch-All ($any) Handler

The `@handle("$any")` decorator creates a catch-all handler that processes any event on the subscribed stream, regardless of event type.

## Overview

The `$any` handler is a fallback. It runs for an event that has no specific `@handle(EventClass)` method on the same handler class. When a specific method exists for the event's type, only that method runs. When neither exists, the handler does nothing with the event. Typical uses are audit logging, metrics, and forwarding events to an external system.

## Code

The complete implementation is in [assets/event_handler_any_event.py](../assets/event_handler_any_event.py).

## How It Works

### Handler Registration

The examples on this page use these elements:

```python
import logging

from protean.exceptions import ObjectNotFoundError

logger = logging.getLogger(__name__)

@domain.aggregate
class Task:
    title: String(required=True)

@domain.event(part_of=Task)
class TaskCreated:
    task_id: Identifier(required=True)
    title: String(required=True)

@domain.aggregate
class AuditLog:
    entry_id: Identifier(identifier=True)
    event_type: String(required=True)
    details: String()
```

Events are delivered at least once, so the same event can arrive again. `AuditLog` takes the audited event's id as its identity, and the handler returns when an entry with that id exists:

```python
@domain.event_handler(part_of=AuditLog, stream_category=Task.meta_.stream_category)
class TaskAuditor:
    @handle("$any")
    def on_any_task_event(self, event):
        repository = domain.repository_for(AuditLog)
        entry_id = event._metadata.headers.id
        try:
            repository.get(entry_id)
        except ObjectNotFoundError:
            repository.add(
                AuditLog(
                    entry_id=entry_id,
                    event_type=event.__class__.__name__,
                    details=f"Event received: {event.__class__.__name__}",
                )
            )
        else:
            return  # already recorded; a redelivered event must not log twice
```

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

A handler that names a specific event belongs to the cluster that owns that event, here Task (a handler in another cluster that names `TaskCreated` is what `check` reports as `EVENT_HANDLER_FOREIGN_EVENT`):

```python
@domain.event_handler(part_of=Task)
class TaskActivityHandler:
    @handle(TaskCreated)
    def on_task_created(self, event: TaskCreated):
        # This handles TaskCreated events specifically
        logger.info("Task created: %s", event.title)

    @handle("$any")
    def on_any_event(self, event):
        # This handles all OTHER events (not TaskCreated)
        logger.info("Task event: %s", event.__class__.__name__)
```

## Related

- [Same-Aggregate](./same-aggregate.md): Basic event handler pattern
- [Cross-Aggregate](./cross-aggregate.md): Cross-aggregate coordination
- [Anti-patterns](./anti-patterns.md): Common mistakes
