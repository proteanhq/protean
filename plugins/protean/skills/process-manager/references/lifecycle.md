# Lifecycle Management

Process managers have a defined lifecycle: they start when an initiating event arrives, progress through intermediate states, and complete when the process reaches a terminal state.

## Overview

The lifecycle is controlled by three parameters on the `@handle` decorator:

- **`start=True`**: Creates a new PM instance when no existing instance is found
- **`end=True`**: Auto-marks the PM as complete after the handler returns, on every path
- **`mark_as_complete()`**: Explicitly marks the PM as complete from within a handler

## Starting a Process

At least one handler must be marked with `start=True`. A PM with none fails at `domain.init()` with `IncorrectUsageError`:

```python
# fragment
@handle(OrderPlaced, start=True, correlate="order_id")
def on_order_placed(self, event: OrderPlaced) -> None:
    self.order_id = event.order_id
    self.status = "awaiting_payment"
```

When a start event arrives:
1. The framework extracts the correlation value from the event
2. Checks if a PM instance already exists for that value
3. If not found, creates a new empty PM instance
4. Runs the handler method on the new instance
5. Persists the resulting state as a transition event

If a **non-start event** arrives and no PM instance exists for the correlation value, the event is **silently skipped**. This prevents orphaned processing when events arrive out of order.

## Completing a Process

### Using `end=True`

The PM is automatically marked complete after the handler runs:

```python
# fragment
@handle(PaymentFailed, correlate="order_id", end=True)
def on_payment_failed(self, event: PaymentFailed) -> None:
    self.status = "cancelled"
    # PM is auto-completed after this handler returns
```

Use `end=True` for unconditional terminal states, where the handler always leads to completion. The PM completes after every normal return from the handler, including an early `return` from a guard, so do not put `end=True` on a handler that completes only on some paths. `check` reports a PM with no `end=True` handler as `PROCESS_MANAGER_UNCLOSED`, so every PM should mark at least one terminating handler this way.

### Using `mark_as_complete()`

Call explicitly within a handler for conditional completion:

```python
# fragment
@handle(ShipmentDelivered, correlate="order_id")
def on_shipment_delivered(self, event: ShipmentDelivered) -> None:
    self.status = "completed"
    self.mark_as_complete()  # Explicit completion
```

Use `mark_as_complete()` when you need to decide whether to complete based on PM state or event data. It does not clear `PROCESS_MANAGER_UNCLOSED` on its own. The diagnostic reads only the `end=True` flag.

## Completed Process Managers

Once a PM is marked complete (either via `end=True` or `mark_as_complete()`):

- **Subsequent events are silently skipped** — No handler runs, no transition is persisted
- **The PM cannot be "reopened"** — There is no mechanism to uncomplete a PM
- **The completion is recorded** — The final transition event has `is_complete=True`

## Code

The complete lifecycle example is in [assets/pm_basic.py](../assets/pm_basic.py).

`OrderFulfillmentPM` demonstrates both completion paths:
- **Failure path**: `PaymentFailed` → `end=True` auto-completes
- **Success path**: `ShipmentDelivered` → `mark_as_complete()` explicit completion

## Transition Events

After each handler runs, the framework auto-generates a **transition event** that captures:

- **`state`**: Dictionary snapshot of all PM field values
- **`handler_name`**: Name of the handler method that ran
- **`is_complete`**: Whether the PM is marked complete

These transition events are stored in the PM's own stream (`{pm_stream_category}-{correlation_value}`).

### Reconstitution

When loading a PM instance, the framework:

1. Reads all transition events from the PM's stream
2. Replays them in order to rebuild the current field state
3. Tracks `_version` (incremented with each transition) and `_is_complete` flag

This makes process managers fully event-sourced — their state is derived from their transition event history.

### Example Transition Event

After `on_payment_confirmed` runs:

```python
{
    "state": {
        "order_id": "ORD-123",
        "payment_id": "PAY-456",
        "status": "awaiting_shipment"
    },
    "handler_name": "on_payment_confirmed",
    "is_complete": False
}
```

## Best Practices

- **Always define at least one terminal state**: Mark at least one handler `end=True`. Without a terminal state, the PM accepts events indefinitely
- **Handle compensation on failure paths** — When a step fails, issue compensating commands to undo earlier steps
- **Design for idempotency** — Events may be delivered more than once; handlers should produce the same outcome

## Related

- [Correlation](./correlation.md) - How events are routed to PM instances
- [Command Issuance](./command-issuance.md) - Issuing commands from PM handlers
- [Anti-patterns](./anti-patterns.md) - Missing terminal states
