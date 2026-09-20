# Error Handling

Event handlers support custom error handling through the optional `handle_error` classmethod. This method is invoked by the Protean Engine when event processing fails during asynchronous operation.

## Overview

When an exception occurs in an event handler method:

1. The Protean Engine catches the exception
2. The engine logs detailed error information with stack traces
3. The engine calls the handler's `handle_error(exc, message)` classmethod
4. Processing continues with the next event (the engine does not shut down)

## Code

See [assets/event_handler_error_handling.py](../assets/event_handler_error_handling.py) for a complete example.

## The handle_error Method

The default `handle_error` implementation (from `HandlerMixin`) does nothing. Override it to add custom behavior:

```python
@domain.event_handler(part_of=ShipmentLog, stream_category=Shipment.meta_.stream_category)
class ShipmentNotifier:
    @handle(ShipmentDispatched)
    def on_shipment_dispatched(self, event: ShipmentDispatched):
        log_entry = ShipmentLog(...)
        domain.repository_for(ShipmentLog).add(log_entry)

    @classmethod
    def handle_error(cls, exc: Exception, message) -> None:
        """Called by the engine when on_shipment_dispatched raises."""
        logger.error(f"Shipment event failed: {exc}")
        # Send alert, record failure metrics, etc.
```

## Method Signature

```python
@classmethod
def handle_error(cls, exc: Exception, message) -> None:
```

- `cls` - The event handler class
- `exc` - The exception that was raised during event handling
- `message` - The original event message (a `Message` object) being processed

## Synchronous vs. Asynchronous

- **Asynchronous processing**: `handle_error` is called by the Protean Engine. The engine catches the exception, logs it, calls `handle_error`, and continues.
- **Synchronous processing** (`event_processing = "sync"`): Exceptions propagate directly. `handle_error` is NOT called -- the caller is responsible for catching exceptions.

## Error Handler Safety

If `handle_error` itself raises an exception, the Protean Engine catches that too and logs it. The engine never shuts down due to handler errors:

```python
@classmethod
def handle_error(cls, exc: Exception, message) -> None:
    # Even if this raises, the engine continues
    external_api.notify(str(exc))  # Might fail, but engine is safe
```

## Best Practices

1. Keep `handle_error` simple and robust -- avoid complex logic that might fail
2. Use it for logging, monitoring, and alerting
3. Do not attempt to re-process the event within `handle_error`
4. Consider recording failed events for later retry or manual intervention

## Related

- [Anti-patterns](./anti-patterns.md) - Common error handling mistakes
- `command-handler` - Command handlers have the same handle_error pattern
