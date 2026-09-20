# Event Versioning

Event versioning enables schema evolution while maintaining backward compatibility. As your domain evolves, events may need new fields, renamed attributes, or changed structures. Proper versioning ensures existing consumers continue to work.

## Overview

Events are long-lived contracts between producers and consumers. Unlike aggregates that can be refactored internally, events published to external systems must maintain compatibility. Event versioning provides a strategy for evolving event schemas safely.

**Why versioning matters:**
- Events are stored in event stores (permanent records)
- Consumers may process old and new versions
- Schema changes should not break existing consumers
- Domain models evolve over time

## Code

The complete implementation is in [assets/event_versioning.py](../assets/event_versioning.py).

Key highlights:
- Use `__version__` class attribute to track schema versions
- Start with "v1" and increment for breaking changes
- Maintain backward compatibility when possible
- Document version changes in event docstrings

## Basic Versioning

Every event should have a `__version__` attribute from the start:

```python
@domain.event(part_of="Order")
class OrderPlaced:
    __version__ = 1  # Always version from the beginning

    order_id: String(required=True, identifier=True)
    customer_id: String(required=True)
    placed_at: DateTime(required=True)
```

## Version Evolution Strategies

### 1. Backward Compatible Changes (Same Version)

Some changes don't require a new version:

**Adding optional fields:**
```python
@domain.event(part_of="Order")
class OrderPlaced:
    __version__ = 1

    order_id: String(required=True, identifier=True)
    customer_id: String(required=True)
    placed_at: DateTime(required=True)
    # New optional field - backward compatible
    notes: String()  # Old events won't have this, default is None
```

**Adding default values:**
```python
@domain.event(part_of="Product")
class ProductCreated:
    __version__ = 1

    product_id: String(required=True, identifier=True)
    name: String(required=True)
    # New field with default - backward compatible
    category: String(default="uncategorized")
```

### 2. Breaking Changes (New Version)

Breaking changes require incrementing the version:

**Adding required fields:**
```python
# v1 - original
@domain.event(part_of="Order")
class OrderPlaced:
    __version__ = 1

    order_id: String(required=True, identifier=True)
    customer_id: String(required=True)

# v2 - added required field
@domain.event(part_of="Order")
class OrderPlaced:
    __version__ = 2

    order_id: String(required=True, identifier=True)
    customer_id: String(required=True)
    total = ValueObject(Money, required=True)  # New required field
```

**Removing fields:**
```python
# v1 - original
@domain.event(part_of="User")
class UserRegistered:
    __version__ = 1

    user_id: String(required=True, identifier=True)
    username: String(required=True)
    email: String(required=True)

# v2 - removed username field
@domain.event(part_of="User")
class UserRegistered:
    __version__ = 2

    user_id: String(required=True, identifier=True)
    email: String(required=True)
    # username field removed
```

**Changing field types:**
```python
# v1 - original
@domain.event(part_of="Product")
class PriceChanged:
    __version__ = 1

    product_id: String(required=True, identifier=True)
    new_price: Float(required=True)  # Simple float

# v2 - changed to value object
@domain.event(part_of="Product")
class PriceChanged:
    __version__ = 2

    product_id: String(required=True, identifier=True)
    new_price = ValueObject(Money, required=True)  # Now a value object
```

## Version Migration Patterns

### Pattern 1: Side-by-side Versions

Create new event types for major changes:

```python
# Old event - still supported
@domain.event(part_of="Order")
class OrderPlaced:
    __version__ = 1

    order_id: String(required=True, identifier=True)
    customer_id: String(required=True)

# New event for new schema
@domain.event(part_of="Order")
class OrderPlacedV2:
    __version__ = 2

    order_id: String(required=True, identifier=True)
    customer_id: String(required=True)
    total = ValueObject(Money, required=True)
    items: List()
```

### Pattern 2: Upcasting

Transform old event versions to new format when reading:

```python
class EventUpcaster:
    """Upcast old event versions to current schema."""

    def upcast(self, event_data: dict, version: str) -> dict:
        if version == "v1":
            # Transform v1 to v2 format
            return self._upcast_v1_to_v2(event_data)
        return event_data

    def _upcast_v1_to_v2(self, event_data: dict) -> dict:
        """Transform OrderPlaced v1 to v2."""
        return {
            **event_data,
            "__version__": 2,
            "total": {"amount": 0.0, "currency": "USD"}  # Default value
        }
```

### Pattern 3: Weak Schema

Use flexible fields for evolving data:

```python
@domain.event(part_of="Order")
class OrderPlaced:
    __version__ = 1

    order_id: String(required=True, identifier=True)
    customer_id: String(required=True)

    # Flexible metadata field for evolution
    metadata: Dict()  # Can add new data without schema changes
```

## Versioning Best Practices

### 1. Always Version from the Start

```python
# Good
@domain.event(part_of="Order")
class OrderPlaced:
    __version__ = 1  # Explicit from day one
    order_id: String(required=True, identifier=True)

# Bad
@domain.event(part_of="Order")
class OrderPlaced:
    # Missing __version__ - assumes default
    order_id: String(required=True, identifier=True)
```

### 2. Document Version Changes

```python
@domain.event(part_of="Order")
class OrderPlaced:
    """Order placement event.

    Version History:
    - v1: Initial version with basic order info
    - v2: Added total and items fields (2024-02-09)
    - v3: Changed price to Money value object (2024-03-15)
    """
    __version__ = 3

    order_id: String(required=True, identifier=True)
    customer_id: String(required=True)
    total = ValueObject(Money, required=True)
    items: List()
```

### 3. Plan for Backward Compatibility

```python
# Good: Add optional fields
@domain.event(part_of="Product")
class ProductCreated:
    __version__ = 1

    product_id: String(required=True, identifier=True)
    name: String(required=True)
    description: String()  # Optional - backward compatible
    tags: List()  # Optional - backward compatible

# Bad: Add required fields to existing version
@domain.event(part_of="Product")
class ProductCreated:
    __version__ = 1  # Still v1 but added required field!

    product_id: String(required=True, identifier=True)
    name: String(required=True)
    category: String(required=True)  # Breaking change without version bump!
```

### 4. Test Multiple Versions

```python
def test_deserialize_v1_event():
    """Ensure old v1 events still deserialize."""
    event_data = {
        "__version__": 1,
        "order_id": "ORD-001",
        "customer_id": "CUST-123"
    }
    event = OrderPlaced(**event_data)
    assert event.order_id == "ORD-001"

def test_deserialize_v2_event():
    """Ensure new v2 events deserialize with new fields."""
    event_data = {
        "__version__": 2,
        "order_id": "ORD-001",
        "customer_id": "CUST-123",
        "total": {"amount": 99.99, "currency": "USD"}
    }
    event = OrderPlaced(**event_data)
    assert event.total.amount == 99.99
```

## Common Versioning Scenarios

### Scenario 1: Adding Optional Enrichment Data

```python
# v1
@domain.event(part_of="Order")
class OrderPlaced:
    __version__ = 1
    order_id: String(required=True, identifier=True)
    customer_id: String(required=True)

# v1 with new optional fields (backward compatible)
@domain.event(part_of="Order")
class OrderPlaced:
    __version__ = 1  # Same version
    order_id: String(required=True, identifier=True)
    customer_id: String(required=True)
    user_agent: String()  # Optional enrichment
    ip_address: String()  # Optional enrichment
```

### Scenario 2: Splitting into Multiple Events

```python
# v1 - monolithic event
@domain.event(part_of="Order")
class OrderUpdated:
    __version__ = 1
    order_id: String(required=True, identifier=True)
    update_type: String(required=True)  # "status", "address", "payment"
    new_value: String()

# v2 - split into focused events
@domain.event(part_of="Order")
class OrderStatusChanged:
    __version__ = 1
    order_id: String(required=True, identifier=True)
    new_status: String(required=True)

@domain.event(part_of="Order")
class OrderAddressChanged:
    __version__ = 1
    order_id: String(required=True, identifier=True)
    new_address = ValueObject(Address, required=True)
```

### Scenario 3: Evolving from Primitives to Value Objects

```python
# v1 - primitive types
@domain.event(part_of="Order")
class OrderPlaced:
    __version__ = 1
    order_id: String(required=True, identifier=True)
    total_amount: Float(required=True)
    currency: String(default="USD")

# v2 - value object
@domain.event(part_of="Order")
class OrderPlaced:
    __version__ = 2
    order_id: String(required=True, identifier=True)
    total = ValueObject(Money, required=True)
```

## Related

- [Delta Events](./delta-events.md) - Incremental state changes
- [Fact Events](./fact-events.md) - Complete state snapshots
- [Anti-patterns](./anti-patterns.md) - Common versioning mistakes
