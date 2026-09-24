# Delta Events

Delta events capture incremental changes that have occurred in the state of an aggregate. They provide detailed information about specific modifications made, rather than the complete state.

## Overview

Delta events are the most common type of event in event-driven systems. They record what changed, not the entire state. This makes them lightweight, focused, and efficient for communication and storage.

**When to use delta events:**
- Recording specific state transitions in aggregates
- Notifying other parts of the system about important changes
- Building event-sourced aggregates (replaying delta events to reconstruct state)
- Creating custom projections and read models
- Triggering side effects in other bounded contexts

## Code

The complete implementation is in [assets/event_simple.py](../assets/event_simple.py).

Key highlights:
- Events are lightweight DTOs with only relevant data
- Named in past-tense to indicate what happened
- Always associated with an aggregate via `part_of`
- Immutable once created

## Characteristics

### 1. Incremental Changes Only

Delta events contain only the data that changed or is necessary to understand the change:

```python
@domain.event(part_of="Order")
class OrderPlaced:
    __version__ = 1

    order_id: String(required=True, identifier=True)
    customer_id: String(required=True)
    placed_at: DateTime(required=True)
    # No need for entire order details - just what's needed
```

### 2. Multiple Event Types per Aggregate

Aggregates typically emit multiple delta event types, each representing a different state transition:

```python
@domain.event(part_of="Order")
class OrderPlaced:
    order_id: String(required=True, identifier=True)
    customer_id: String(required=True)
    placed_at: DateTime(required=True)

@domain.event(part_of="Order")
class OrderShipped:
    order_id: String(required=True, identifier=True)
    shipped_at: DateTime(required=True)
    tracking_number: String(required=True)

@domain.event(part_of="Order")
class OrderCancelled:
    order_id: String(required=True, identifier=True)
    cancelled_at: DateTime(required=True)
    reason: String(required=True)
```

### 3. Focused and Purposeful

Each delta event has a clear, focused purpose - it describes one thing that happened:

```python
# Good: Focused event
@domain.event(part_of="Inventory")
class StockDepleted:
    __version__ = 1

    product_id: String(required=True, identifier=True)
    depleted_at: DateTime(required=True)
    previous_quantity: Integer(required=True)
```

## When to Use Delta Events vs Fact Events

| Scenario | Use Delta Events | Use Fact Events |
|----------|------------------|-----------------|
| Event Sourcing | ✓ (reconstruct state by replaying) | × (too heavy) |
| Internal projections | ✓ (custom read models) | Sometimes |
| External consumers | Sometimes | ✓ (don't want to track history) |
| Audit trail | ✓ (detailed change log) | × |
| Cross-context communication | Depends | ✓ (simpler for consumers) |

## Examples from Different Domains

### E-Commerce Order

```python
@domain.event(part_of="Order")
class OrderPlaced:
    __version__ = 1
    order_id: String(required=True, identifier=True)
    customer_id: String(required=True)
    total_amount: Float(required=True)
    placed_at: DateTime(required=True)

@domain.event(part_of="Order")
class OrderItemAdded:
    __version__ = 1
    order_id: String(required=True, identifier=True)
    product_id: String(required=True)
    quantity: Integer(required=True)
    unit_price: Float(required=True)
```

### Banking Account

```python
@domain.event(part_of="Account")
class MoneyDeposited:
    __version__ = 1
    account_id: String(required=True, identifier=True)
    amount: Float(required=True)
    deposited_at: DateTime(required=True)
    transaction_id: String(required=True)

@domain.event(part_of="Account")
class MoneyWithdrawn:
    __version__ = 1
    account_id: String(required=True, identifier=True)
    amount: Float(required=True)
    withdrawn_at: DateTime(required=True)
    transaction_id: String(required=True)
```

### Inventory Management

```python
@domain.event(part_of="Stock")
class StockReserved:
    __version__ = 1
    product_id: String(required=True, identifier=True)
    quantity: Integer(required=True)
    order_id: String(required=True)
    reserved_at: DateTime(required=True)

@domain.event(part_of="Stock")
class StockReleased:
    __version__ = 1
    product_id: String(required=True, identifier=True)
    quantity: Integer(required=True)
    order_id: String(required=True)
    released_at: DateTime(required=True)
```

## Best Practices

1. **Keep events focused** - One event per state transition
2. **Include timestamps** - Always include when the event occurred
3. **Include identifiers** - Make events traceable (order_id, customer_id, etc.)
4. **Version from the start** - Always include `__version__` for future evolution
5. **Document the meaning** - Use clear names and docstrings

## Related

- [Fact Events](./fact-events.md) - Complete state snapshots
- [Event Versioning](./event-versioning.md) - Handling schema evolution
- [Raising Events](./raising-events.md) - How to emit events from aggregates
