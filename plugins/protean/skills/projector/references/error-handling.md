# Error Handling in Projectors

## Overview

Projectors may encounter errors while processing events - network failures, data inconsistencies, missing records. Protean provides the `handle_error` classmethod for custom error recovery, similar to event handlers. Proper error handling ensures that projection failures don't crash the system.

## The handle_error classmethod

Override the `handle_error` classmethod on a projector class to define custom error recovery:

```python
@domain.projector(projector_for=ProductInventory, aggregates=[Product])
class ProductInventoryProjector:
    @on(ProductAdded)
    def on_product_added(self, event: ProductAdded):
        repo = domain.repository_for(ProductInventory)
        inventory = ProductInventory(
            product_id=event.product_id,
            name=event.name,
            stock_quantity=event.stock_quantity,
        )
        repo.add(inventory)

    @classmethod
    def handle_error(cls, exc: Exception, message) -> None:
        logger.error(f"Projection update failed: {exc}, message: {message}")
```

### Method signature

```python
@classmethod
def handle_error(cls, exc: Exception, message) -> None:
```

- `cls`: The projector class itself
- `exc`: The exception that was raised
- `message`: The event message that caused the error
- Returns `None` - error handlers don't return values

## Synchronous vs asynchronous processing

### Synchronous processing (`event_processing = "sync"`)
- Errors propagate immediately to the caller
- `handle_error` is NOT called in sync mode
- Useful for testing and development

### Asynchronous processing (production)
- The Protean engine catches exceptions from projector methods
- Calls `handle_error` if defined on the projector class
- The engine never shuts down due to projector errors
- Errors are logged and processing continues

## Best practices

1. **Log errors with context**: Include the event data and projection state in error logs
2. **Don't re-raise in handle_error**: The engine handles the error lifecycle
3. **Consider idempotency**: Design projector methods to handle duplicate events
4. **Handle missing projections**: Use try/except for projection lookups that may fail

```python
@on(StockAdjusted)
def on_stock_adjusted(self, event: StockAdjusted):
    repo = domain.repository_for(ProductInventory)
    try:
        inventory = repo.get(event.product_id)
        inventory.stock_quantity = event.new_stock_quantity
        repo.add(inventory)
    except Exception:
        # Log and handle gracefully
        logger.warning(f"Inventory not found for product {event.product_id}")
```

## Complete example

See [projector_error_handling.py](../assets/projector_error_handling.py) for a complete, runnable example.

## Related

- [Single-Aggregate Projector](single-aggregate.md) - Basic projector pattern
- [Anti-patterns](anti-patterns.md) - Common mistakes to avoid
- `event-handler` - Event handlers have a similar error handling pattern
