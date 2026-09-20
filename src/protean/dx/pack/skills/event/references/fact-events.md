# Fact Events

Fact events contain the complete state of an aggregate at a specific point in time. They enable the Event-carried State Transfer pattern, where consumers receive all necessary information without needing to track history or query for additional data.

## Overview

Unlike delta events that capture incremental changes, fact events provide a complete snapshot of aggregate state. This simplifies consumption for external systems that don't need to maintain event history or reconstruct state from multiple events.

**When to use fact events:**
- Communicating with external bounded contexts or systems
- When consumers shouldn't build state from multiple delta events
- Providing read models to external APIs or services
- Simplifying consumer logic (no need to track event history)
- Creating periodic snapshots for performance optimization

## Code

The complete implementation is in [assets/event_fact.py](../assets/event_fact.py).

Key highlights:
- Contains complete aggregate state
- Enables Event-carried State Transfer pattern
- Simplifies consumer logic
- Larger payload but simpler consumption

## Event-carried State Transfer Pattern

The Event-carried State Transfer pattern means that events carry enough information for consumers to maintain their own local copy of data without needing to query back to the source system.

### Benefits

1. **Reduced coupling** - Consumers don't need to call back to the producer
2. **Improved performance** - All data is in the event, no additional queries needed
3. **Simplified consumer logic** - No need to track and replay multiple events
4. **Better availability** - Consumers work even if producer is down

### Trade-offs

1. **Larger events** - More data in each event
2. **Data duplication** - Same data sent to multiple consumers
3. **Eventual consistency** - Consumers may temporarily have stale data
4. **Schema evolution** - Changes affect all consumers

## Characteristics

### 1. Complete State

Fact events include all attributes needed to fully describe the aggregate:

```python
@domain.event(part_of="Order")
class OrderSnapshot:
    """Complete order state at a point in time."""
    __version__ = 1

    # Identity
    order_id: String(required=True, identifier=True)
    customer_id: String(required=True)

    # State
    status: String(required=True)

    # Complete data
    items: List()  # All order items
    total = ValueObject(Money, required=True)

    # Timestamps
    placed_at: DateTime()
    shipped_at: DateTime()
    delivered_at: DateTime()
    cancelled_at: DateTime()

    # Additional context
    shipping_address = ValueObject(Address)
    billing_address = ValueObject(Address)
```

### 2. Self-contained Information

Consumers can understand the complete state without additional context:

```python
@domain.event(part_of="Customer")
class CustomerProfileUpdated:
    """Complete customer profile for external systems."""
    __version__ = 1

    customer_id: String(required=True, identifier=True)
    email: String(required=True)
    full_name: String(required=True)
    phone: String()

    # Complete address info
    address = ValueObject(Address, required=True)

    # Account status
    status: String(required=True)
    account_type: String(required=True)

    # Preferences
    preferences: Dict()

    # Metadata
    created_at: DateTime(required=True)
    updated_at: DateTime(required=True)
```

## When to Use Fact Events

### Use Fact Events When:

1. **External consumers** - Other bounded contexts or systems need current state
2. **Simplified consumption** - Consumers shouldn't need to maintain event history
3. **Periodic snapshots** - Send complete state at intervals
4. **Integration events** - Publishing to external systems or APIs

### Use Delta Events When:

1. **Event sourcing** - Reconstructing state by replaying events
2. **Internal projections** - Building custom read models from event stream
3. **Audit trail** - Detailed change history required
4. **Minimal data transfer** - Bandwidth or storage constraints

### Hybrid Approach

Many systems use both:
- **Delta events** for internal event sourcing and projections
- **Fact events** for external communication and integration

```python
# Internal delta events
@domain.event(part_of="Order")
class OrderPlaced:
    order_id: String(required=True, identifier=True)
    customer_id: String(required=True)
    placed_at: DateTime(required=True)

@domain.event(part_of="Order")
class OrderShipped:
    order_id: String(required=True, identifier=True)
    shipped_at: DateTime(required=True)

# External fact event
@domain.event(part_of="Order")
class OrderStatusChanged:
    """Published to external systems with complete state."""
    __version__ = 1

    order_id: String(required=True, identifier=True)
    customer_id: String(required=True)
    status: String(required=True)
    items: List()
    total = ValueObject(Money)
    placed_at: DateTime()
    shipped_at: DateTime()
```

## Examples

### E-Commerce Order Snapshot

```python
@domain.value_object
class Money:
    amount: Float(required=True)
    currency: String(max_length=3, default="USD")

@domain.value_object
class Address:
    street: String(required=True, max_length=200)
    city: String(required=True, max_length=100)
    state: String(max_length=50)
    postal_code: String(required=True, max_length=20)
    country: String(required=True, max_length=50)

@domain.event(part_of="Order")
class OrderSnapshot:
    """Complete order state for external systems."""
    __version__ = 1

    order_id: String(required=True, identifier=True)
    customer_id: String(required=True)
    status: String(required=True)

    items: List()  # Complete order items
    total = ValueObject(Money, required=True)
    subtotal = ValueObject(Money)
    tax = ValueObject(Money)
    shipping_cost = ValueObject(Money)

    shipping_address = ValueObject(Address, required=True)
    billing_address = ValueObject(Address)

    placed_at: DateTime()
    shipped_at: DateTime()
    delivered_at: DateTime()
```

### Customer Profile Snapshot

```python
@domain.event(part_of="Customer")
class CustomerSnapshot:
    """Complete customer information for CRM integration."""
    __version__ = 1

    customer_id: String(required=True, identifier=True)
    email: String(required=True, max_length=255)
    full_name: String(required=True, max_length=200)
    phone: String(max_length=20)

    # Complete address
    primary_address = ValueObject(Address)

    # Account details
    status: String(required=True)
    account_type: String(required=True)
    loyalty_tier: String()

    # Metadata
    created_at: DateTime(required=True)
    last_login_at: DateTime()
    total_orders: Integer(default=0)
    lifetime_value = ValueObject(Money)
```

## Raising Fact Events

Fact events are typically raised at specific milestones or on a schedule:

```python
@domain.aggregate
class Order:
    order_id: String(required=True, identifier=True)
    customer_id: String(required=True)
    status: String(default="draft")
    items = HasMany("OrderItem")
    total = ValueObject(Money)

    def publish_snapshot(self):
        """Publish complete order state for external consumers."""
        self.raise_(OrderSnapshot(
            order_id=self.order_id,
            customer_id=self.customer_id,
            status=self.status,
            items=[item.to_dict() for item in self.items],
            total=self.total,
            placed_at=self.placed_at,
            shipped_at=self.shipped_at,
            delivered_at=self.delivered_at
        ))
```

## Best Practices

1. **Use descriptive names** - "Snapshot", "StateChanged", "Updated" indicate complete state
2. **Version carefully** - Schema changes affect all consumers
3. **Include timestamps** - When was this snapshot taken?
4. **Don't over-use** - Fact events are heavier than delta events
5. **Document consumer expectations** - What data consumers should use

## Related

- [Delta Events](./delta-events.md) - Incremental state changes
- [With Value Objects](./with-value-objects.md) - Using value objects in events
- [Raising Events](./raising-events.md) - How to emit events from aggregates
