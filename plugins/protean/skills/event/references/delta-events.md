# Delta Events

Delta events capture one incremental change to an aggregate's state: what changed, not the complete state. Most events are delta events.

The complete implementation is in [assets/event_simple.py](../assets/event_simple.py).

## Characteristics

The events on this page belong to this aggregate:

```python
@domain.aggregate
class Order:
    customer_id: String(required=True)
    status: String(default="draft")
```

### Multiple Event Types per Aggregate

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

## When to Use Delta Events vs Fact Events

| Scenario | Use Delta Events | Use Fact Events |
|----------|------------------|-----------------|
| Event Sourcing | ✓ (reconstruct state by replaying) | × (too heavy) |
| Internal projections | ✓ (custom read models) | Sometimes |
| External consumers | Sometimes | ✓ (don't want to track history) |
| Audit trail | ✓ (detailed change log) | × |
| Cross-context communication | Depends | ✓ (simpler for consumers) |

## Related

- [Fact Events](./fact-events.md): Complete state snapshots
- [Event Versioning](./event-versioning.md): Handling schema evolution
- [Raising Events](./raising-events.md): How to emit events from aggregates
