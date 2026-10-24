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

The default `handle_error` implementation (from `HandlerMixin`) does nothing. Override it to add custom behavior. The example uses these elements, shortened from the asset:

```python
import logging

logger = logging.getLogger(__name__)

@domain.aggregate
class Shipment:
    order_id: Identifier(required=True)
    status: String(default="pending")

@domain.event(part_of=Shipment)
class ShipmentDispatched:
    shipment_id: Identifier(required=True)

@domain.aggregate
class ShipmentLog:
    log_id: Identifier(identifier=True)
    shipment_id: Identifier(required=True)
    message: Text(required=True)

@domain.command(part_of=ShipmentLog)
class RecordShipmentLog:
    log_id: Identifier(required=True)
    shipment_id: Identifier(required=True)
    message: Text(required=True)
```

```python
@domain.event_handler(part_of=Shipment)
class ShipmentNotifier:
    @handle(ShipmentDispatched)
    def on_shipment_dispatched(self, event: ShipmentDispatched):
        current_domain.process(
            RecordShipmentLog(
                log_id=f"{event.shipment_id}:dispatched",
                shipment_id=event.shipment_id,
                message=f"Shipment {event.shipment_id} dispatched",
            )
        )

    @classmethod
    def handle_error(cls, exc: Exception, message) -> None:
        """Called by the engine when on_shipment_dispatched raises."""
        logger.error(f"Shipment event failed: {exc}")
        # Send alert, record failure metrics, etc.
```

The handler sits in Shipment's cluster, which owns `ShipmentDispatched`, and writes the log entry through a `RecordShipmentLog` command to ShipmentLog.

## Method Signature

```python
# fragment
@classmethod
def handle_error(cls, exc: Exception, message) -> None:
```

- `cls`: The event handler class
- `exc`: The exception that was raised during event handling. When several `@handle` methods on the same handler fail for one event, it is an `ExceptionGroup` with one entry per failure, so code that matches on the exception type has to look inside `exc.exceptions`
- `message`: The original event message (a `Message` object) being processed

## Synchronous vs. Asynchronous

With `event_processing = "sync"`, exceptions propagate to the caller and `handle_error` is NOT called. The caller catches them.

## Error Handler Safety

If `handle_error` itself raises an exception, the Protean Engine catches that too and logs it.

## Best Practices

Use `handle_error` for logging, monitoring and alerting. Do not re-process the event inside it.

## Related

- [Anti-patterns](./anti-patterns.md): Common mistakes
- `command-handler`: Command handlers have the same handle_error pattern
