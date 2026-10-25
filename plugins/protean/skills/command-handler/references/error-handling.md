# Error Handling

The Protean Engine calls a command handler's optional `handle_error` classmethod when the handler fails during asynchronous processing.

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
import logging

from protean import handle
from protean.fields import Decimal, Identifier, String

logger = logging.getLogger(__name__)

@domain.aggregate
class Payment:
    payment_id: Identifier(identifier=True)
    amount: Decimal(precision=19, scale=4, required=True)
    status: String(default="pending")

    def execute(self):
        if self.amount <= 0:
            raise ValueError("Transfer amount must be positive")
        self.status = "completed"

@domain.command(part_of="Payment")
class TransferFunds:
    payment_id: Identifier(required=True)
    amount: Decimal(precision=19, scale=4, required=True)

@domain.command_handler(part_of=Payment)
class PaymentCommandHandler:
    @handle(TransferFunds)
    def handle_transfer(self, command: TransferFunds):
        payment = Payment(payment_id=command.payment_id, amount=command.amount)
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
# fragment
@classmethod
def handle_error(cls, exc: Exception, message) -> None:
```

- `cls`: The command handler class
- `exc`: The exception that was raised during command handling
- `message`: The original command message (a `Message` object) being processed

## Synchronous vs. Asynchronous

- **Asynchronous processing**: `handle_error` is called by the Protean Engine. The engine catches the exception, logs it, calls `handle_error`, and continues.
- **Synchronous processing** (`domain.process(cmd, asynchronous=False)`): Exceptions propagate directly to the caller, and `handle_error` is NOT called. The caller catches the exception.

```python
domain.init(traverse=False)

with domain.domain_context():
    try:
        domain.process(
            TransferFunds(payment_id="PAY-001", amount=0), asynchronous=False
        )
    except ValueError as exc:
        print(f"Transfer rejected: {exc}")  # Transfer amount must be positive
```

## Error Handler Safety

If `handle_error` itself raises an exception, the Protean Engine catches and logs that too (`engine.error_handler_failed`). A handler error never shuts the engine down:

```python
# fragment
@classmethod
def handle_error(cls, exc: Exception, message) -> None:
    # Even if this raises, the engine continues
    external_api.notify(str(exc))  # Might fail, but engine is safe
```

## Related

- [Unit of Work](./unit-of-work.md): Transaction rollback on errors
- [Anti-patterns](./anti-patterns.md): Common error handling mistakes
