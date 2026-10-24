# Subscriber Error Handling

Custom error recovery for subscribers via the `handle_error` classmethod.

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
        # The message may be None or malformed
        product_id = message.get("product_id", "unknown") if message else "unknown"
        logger.error("Failed to process inventory update for %s: %s", product_id, exc)
```

### Key Points

1. `handle_error` is a **classmethod**: it receives `cls`, not `self`
2. It takes two arguments: the exception and the original message
3. If `handle_error` itself raises an exception, the engine catches and logs it, and still moves on to the next message
4. The default implementation (inherited from BaseSubscriber) does nothing

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

## Related

- [Basic Subscriber](./basic-subscriber.md): Subscriber without error handling
- [Anti-corruption Layer](./anti-corruption-layer.md): Error handling during translation
- [Anti-patterns](./anti-patterns.md): Common error handling mistakes
