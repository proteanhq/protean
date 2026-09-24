# Error Handling

Command handlers support custom error handling through the optional `handle_error` classmethod. This method is invoked by the Protean Engine when command processing fails during asynchronous operation.

## Overview

When an exception occurs in a command handler method:

1. The Protean Engine catches the exception
2. The engine logs detailed error information with stack traces
3. The engine calls the handler's `handle_error(exc, message)` classmethod
4. Processing continues with the next command (the engine does not shut down)

## Code

See [assets/command_handler_error_handling.py](../assets/command_handler_error_handling.py) for a complete example.

## The handle_error Method

The default `handle_error` implementation (from `HandlerMixin`) does nothing. Override it to add custom behavior:

```python
@domain.command_handler(part_of=Payment)
class PaymentCommandHandler:
    @handle(TransferFunds)
    def handle_transfer(self, command: TransferFunds):
        payment = Payment(...)
        payment.execute()
        domain.repository_for(Payment).add(payment)

    @classmethod
    def handle_error(cls, exc: Exception, message) -> None:
        """Called by the engine when handle_transfer raises."""
        logger.error(f"Payment failed: {exc}")
        # Send alert, record failure metrics, etc.
```

## Method Signature

```python
@classmethod
def handle_error(cls, exc: Exception, message) -> None:
```

- `cls` - The command handler class
- `exc` - The exception that was raised during command handling
- `message` - The original command message (a `Message` object) being processed

## Synchronous vs. Asynchronous

- **Asynchronous processing**: `handle_error` is called by the Protean Engine. The engine catches the exception, logs it, calls `handle_error`, and continues.
- **Synchronous processing** (`domain.process(cmd, asynchronous=False)`): Exceptions propagate directly to the caller. `handle_error` is NOT called in this case -- the caller is responsible for catching exceptions.

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
3. Do not attempt to re-process the command within `handle_error`
4. Consider recording failed commands for later retry or manual intervention

## Related

- [Unit of Work](./unit-of-work.md) - Transaction rollback on errors
- [Anti-patterns](./anti-patterns.md) - Common error handling mistakes
