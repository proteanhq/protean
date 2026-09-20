# Event Design Guide

How to design domain events when introducing event-driven coordination.

## Event Naming

Use past tense — events describe what already happened:

| Action | Event name |
|--------|-----------|
| Place an order | `OrderPlaced` |
| Ship a package | `PackageShipped` |
| Cancel subscription | `SubscriptionCancelled` |
| Approve request | `RequestApproved` |

## What to Include in Events

### The Goldilocks principle

- **Too thin**: Only the aggregate ID — forces consumers to look up the source aggregate
- **Too fat**: The entire aggregate state — couples consumers to the full schema
- **Just right**: The changed data plus context needed by known consumers

### Include

- **Identity**: The source aggregate's ID (always)
- **Changed data**: Fields that changed as part of this action
- **Context for consumers**: Data that known event handlers will need (avoids round-trips)

### Exclude

- **Internal state**: Implementation details of the source aggregate
- **Computed values**: Things consumers can derive from what you provide
- **Unrelated data**: Fields that didn't change and aren't needed by consumers

### Example

```python
# Good: includes what handlers need
@domain.event(part_of="Order")
class OrderPlaced:
    order_id = Identifier(required=True)
    customer_id = String(required=True)     # Notification handler needs this
    product_id = String(required=True)       # Inventory handler needs this
    quantity = Integer(required=True)         # Inventory handler needs this
    total_amount = Float(required=True)       # Analytics might need this

# Bad: too thin
@domain.event(part_of="Order")
class OrderPlaced:
    order_id = Identifier(required=True)
    # Every handler has to load the Order to get product_id, quantity, etc.

# Bad: too fat
@domain.event(part_of="Order")
class OrderPlaced:
    order_id = Identifier(required=True)
    customer_id = String()
    product_id = String()
    quantity = Integer()
    total_amount = Float()
    status = String()
    created_at = DateTime()
    updated_at = DateTime()
    _version = Integer()
    shipping_address_street = String()  # Not needed by known handlers
    # ... 15 more fields
```

## One Event per State Change

Each distinct business action gets its own event. Don't combine unrelated actions:

```python
# Good: separate events
class OrderPlaced: ...
class OrderShipped: ...
class OrderCancelled: ...

# Bad: generic event with action type
class OrderUpdated:
    action = String()  # "placed", "shipped", "cancelled"
    # Consumers must parse the action string
```

## Event Flow Topology

Design event flows as directed acyclic graphs (DAGs) — never circular:

```
Order ─── OrderPlaced ──┬──> Inventory (reserve stock)
                        ├──> Notification (send confirmation)
                        └──> Analytics (track conversion)

Payment ── PaymentProcessed ──> Order (mark as paid)
```

If A's events trigger changes in B, and B's events trigger changes in A, you have a
circular dependency. Break it by introducing a process manager or rethinking boundaries.

## Related

- [anti-patterns.md](anti-patterns.md) — Event introduction mistakes
