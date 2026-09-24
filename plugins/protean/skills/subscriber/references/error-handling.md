# Subscriber Error Handling

Custom error recovery for subscribers via the `handle_error` classmethod.

## Overview

Subscribers can override the `handle_error` classmethod to provide custom error handling when message processing fails. This is called by the Protean Engine during asynchronous processing, allowing you to log errors, send alerts, or perform cleanup without crashing the message processing pipeline.

## Code

The complete implementation is in [assets/subscriber_error_handling.py](../assets/subscriber_error_handling.py).

Key highlights:
- `handle_error(cls, exc, message)` is a classmethod on the subscriber
- Called by the Protean Engine when `__call__` raises an exception
- In synchronous mode, exceptions propagate directly (handle_error is not called automatically)
- The default implementation in BaseSubscriber does nothing

## How Error Handling Works

### Asynchronous Mode (Production)

```
Message arrives from broker
    -> Engine calls subscriber.__call__(payload)
        -> Exception raised!
    -> Engine catches exception and logs it
    -> Engine calls subscriber.handle_error(exc, message)
    -> Processing continues with next message
```

### Synchronous Mode (Testing)

```
domain.brokers["default"].publish("stream", payload)
    -> subscriber.__call__(payload) called immediately
        -> Exception raised!
    -> Exception propagates to caller (handle_error NOT called)
```

## The handle_error Method

```python
@domain.subscriber(stream="inventory_updates")
class InventoryUpdateSubscriber:
    def __call__(self, payload: dict) -> None:
        # Processing logic that may raise exceptions
        ...

    @classmethod
    def handle_error(cls, exc: Exception, message: dict) -> None:
        """Called by the engine when __call__ raises an exception.

        Args:
            exc: The exception that was raised
            message: The original message dict that caused the error
        """
        product_id = message.get("product_id", "unknown") if message else "unknown"
        logger.error("Failed to process inventory update for %s: %s", product_id, exc)
```

### Key Points

1. `handle_error` is a **classmethod** -- it receives `cls`, not `self`
2. It takes two arguments: the exception and the original message
3. If `handle_error` itself raises an exception, the engine catches and logs it
4. The engine continues processing the next message regardless
5. The default implementation (inherited from BaseSubscriber) does nothing

## Patterns

### Logging with Context

```python
@classmethod
def handle_error(cls, exc: Exception, message: dict) -> None:
    logger.error(
        "Subscriber %s failed: %s | message: %s",
        cls.__name__,
        str(exc),
        message,
    )
```

### Defensive Message Access

```python
@classmethod
def handle_error(cls, exc: Exception, message: dict) -> None:
    # Message may be None or malformed
    order_id = message.get("order_id", "unknown") if message else "unknown"
    logger.error("Failed for order %s: %s", order_id, exc)
```

## Related

- [Basic Subscriber](./basic-subscriber.md) - Subscriber without error handling
- [Anti-corruption Layer](./anti-corruption-layer.md) - Error handling during translation
- [Anti-patterns](./anti-patterns.md) - Common error handling mistakes
