---
name: event
description: Define a Protean domain event - an immutable fact representing a state change in the business domain. Events capture meaningful changes to aggregates and enable decoupled communication between system components. Events are always associated with aggregates and are named in past-tense (OrderPlaced, CustomerRegistered). Use when you need to record what happened in your domain, when you want to communicate state changes to other parts of the system, when the user asks to "create an event", "define a domain event", "add an event", when implementing event sourcing or CQRS patterns, or when they describe something that occurred (like "order was placed", "payment confirmed", "inventory depleted"). Events can be delta events (incremental changes) or fact events (complete state snapshots).
license: Apache-2.0
compatibility: Requires Python 3.11+, protean framework
metadata:
  author: proteanhq
  version: "0.1"
  category: element
---

# Event

## Basic structure

An event is defined using the `@domain.event(part_of="...")` decorator:

```python
from protean import Domain
from protean.fields import String, DateTime

domain = Domain()

@domain.event(part_of="Order")
class OrderPlaced:
    __version__ = 1

    order_id: String(required=True, identifier=True)
    customer_id: String(required=True)
    placed_at: DateTime(required=True)
```

## Key rules

1. **Events must be associated with aggregates** - Always specify `part_of` parameter with the aggregate name
2. **Events are named in past-tense** - Use past-tense verbs: `OrderPlaced`, not `PlaceOrder`
3. **Events are immutable** - Once created, events cannot be modified (they are facts)
4. **Events are DTOs** - Can contain simple fields and value objects, but NOT entities or aggregates
5. **Events should be lightweight** - Include only data necessary to describe what happened
6. **Events are versioned** - Use `__version__` class attribute for schema evolution (defaults to `1`)
7. **Events have metadata** - Protean automatically adds timestamps, unique IDs, and versioning
8. **Events are raised from aggregates** - Use `self.raise_()` method within aggregate methods
9. **Events are persisted to streams** - Events are written to aggregate-specific streams
10. **Events enable decoupling** - Other components react to events via event handlers

## Event types

### Delta Events
Delta events capture incremental changes to aggregate state. Most events are delta events.

```python
@domain.event(part_of="Order")
class OrderPlaced:
    order_id: String(required=True, identifier=True)
    customer_id: String(required=True)
    total_amount: Float(required=True)
```

### Fact Events
Fact events contain complete aggregate state at a point in time (Event-carried State Transfer pattern).

```python
@domain.event(part_of="Order")
class OrderSnapshot:
    """Complete order state for consumers."""
    order_id: String(required=True, identifier=True)
    customer_id: String(required=True)
    status: String(required=True)
    items: List()  # Full state
    total = ValueObject(Money)
```

## Fields and versioning

### Simple Fields

```python
from protean.fields import String, Integer, Float, DateTime, Boolean

@domain.event(part_of="Product")
class ProductCreated:
    __version__ = 1

    product_id: String(required=True, identifier=True)
    name: String(required=True, max_length=200)
    price: Float(required=True)
    created_at: DateTime(required=True)
```

### With Value Objects

Events can contain value objects for complex immutable data:

```python
@domain.value_object
class Money:
    amount: Float(required=True)
    currency: String(max_length=3, default="USD")

@domain.event(part_of="Order")
class OrderPlaced:
    __version__ = 1

    order_id: String(required=True, identifier=True)
    customer_id: String(required=True)
    total = ValueObject(Money, required=True)
    placed_at: DateTime(required=True)
```

### Event Versioning

Use `__version__` for schema evolution:

```python
@domain.event(part_of="Order")
class OrderPlaced:
    __version__ = 1

    order_id: String(required=True, identifier=True)
    customer_id: String(required=True)

# Later, when schema evolves
@domain.event(part_of="Order")
class OrderPlaced:
    __version__ = 2

    order_id: String(required=True, identifier=True)
    customer_id: String(required=True)
    total = ValueObject(Money)  # New field in v2
```

## Raising events from aggregates

Events are raised within aggregate methods using `self.raise_()`:

```python
from datetime import datetime, timezone

@domain.aggregate
class Order:
    order_id: String(required=True, identifier=True)
    customer_id: String(required=True)
    status: String(default="draft")
    total = ValueObject(Money)

    def place(self):
        if self.status != "draft":
            raise ValueError("Order already placed")

        self.status = "placed"
        placed_at = datetime.now(timezone.utc)

        # Raise event - automatically associated with this aggregate instance
        self.raise_(OrderPlaced(
            order_id=self.order_id,
            customer_id=self.customer_id,
            total=self.total,
            placed_at=placed_at
        ))
```

## Quick example

```python
from protean import Domain
from protean.fields import String, Float, DateTime, ValueObject
from datetime import datetime, timezone

domain = Domain()

@domain.value_object
class Money:
    amount: Float(required=True)
    currency: String(max_length=3, default="USD")

@domain.event(part_of="Order")
class OrderPlaced:
    __version__ = 1

    order_id: String(required=True, identifier=True)
    customer_id: String(required=True)
    total = ValueObject(Money, required=True)
    placed_at: DateTime(required=True)

@domain.aggregate
class Order:
    order_id: String(required=True, identifier=True)
    customer_id: String(required=True)
    status: String(default="draft")
    total = ValueObject(Money)

    def place(self):
        if not self.total or self.total.amount <= 0:
            raise ValueError("Order must have a positive total")
        if self.status != "draft":
            raise ValueError("Order already placed")

        self.status = "placed"

        # Raise event
        self.raise_(OrderPlaced(
            order_id=self.order_id,
            customer_id=self.customer_id,
            total=self.total,
            placed_at=datetime.now(timezone.utc)
        ))

# Usage
order = Order(
    order_id="ORD-001",
    customer_id="CUST-123",
    total=Money(amount=99.99, currency="USD")
)
order.place()
print(f"Order {order.order_id} placed. Events: {len(order._events)}")
```

## Common mistakes

### ❌ Using imperative verbs instead of past-tense

```python
@domain.event(part_of="Order")
class PlaceOrder:  # Wrong! This is a command name
    pass
```

✅ **Instead: Use past-tense verbs**

```python
@domain.event(part_of="Order")
class OrderPlaced:  # Correct! Past-tense
    pass
```

### ❌ Not associating event with aggregate

```python
@domain.event  # Wrong! Missing part_of
class OrderPlaced:
    pass
```

✅ **Instead: Always specify part_of**

```python
@domain.event(part_of="Order")  # Correct!
class OrderPlaced:
    pass
```

### ❌ Including entities in events

```python
@domain.event(part_of="Order")
class OrderPlaced:
    order_entity = HasOne(OrderEntity)  # Wrong! Events can't contain entities
```

✅ **Instead: Only fields and value objects**

```python
@domain.event(part_of="Order")
class OrderPlaced:
    order_id: String(required=True, identifier=True)
    total = ValueObject(Money)  # OK - value objects are allowed
```

### ❌ Including too much unnecessary data

```python
@domain.event(part_of="Order")
class OrderPlaced:
    # Including entire customer object when only ID is needed
    customer_name: String()
    customer_email: String()
    customer_address: String()
    customer_phone: String()
```

✅ **Instead: Only necessary information**

```python
@domain.event(part_of="Order")
class OrderPlaced:
    customer_id: String(required=True)  # Just the ID
```

### ❌ Making events mutable

```python
event = OrderPlaced(order_id="123", customer_id="456")
event.order_id = "789"  # Wrong! Events are immutable
```

✅ **Instead: Events are immutable facts**

```python
event = OrderPlaced(order_id="123", customer_id="456")
# Cannot modify - event is immutable and represents what happened
```

## Detailed references

### Core Concepts
- [Delta Events](references/delta-events.md) - Incremental state changes
- [Fact Events](references/fact-events.md) - Complete state snapshots (Event-carried State Transfer)
- [Events with Value Objects](references/with-value-objects.md) - Using value objects in events
- [Event Versioning](references/event-versioning.md) - Schema evolution and version management
- [Raising Events](references/raising-events.md) - How to raise events from aggregates
- [Anti-patterns](references/anti-patterns.md) - Common mistakes and how to avoid them

### Complete Examples
- [Simple Delta Event](assets/event_simple.py) - Basic event with minimal fields
- [Event with Value Objects](assets/event_with_value_object.py) - Events containing value objects
- [Fact Event](assets/event_fact.py) - Complete state snapshot event
- [Event Versioning](assets/event_versioning.py) - Schema evolution examples
- [Raising Events](assets/raising_events.py) - Complete example with aggregate raising events

### Related Skills
- `aggregate` - Events are always part of aggregates
- `value-object` - Events can contain value objects
- `event-handler` - How events are consumed and processed
- `patterns/event-sourcing` - Using events as the source of truth
- `patterns/cqrs` - Using events for read model updates
