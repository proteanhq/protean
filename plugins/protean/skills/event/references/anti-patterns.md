# Event Anti-Patterns

Common mistakes when working with events and how to avoid them.

## Overview

Events are deceptively simple but have specific constraints that, when violated, lead to fragile designs. This guide covers the most common anti-patterns and their correct alternatives.

## 1. Using Imperative Verbs Instead of Past-Tense

### ❌ Wrong

```python
@domain.event(part_of="Order")
class PlaceOrder:  # Imperative verb - this is a COMMAND, not an event!
    order_id: String(required=True)
```

```python
@domain.event(part_of="Payment")
class ProcessPayment:  # Wrong - sounds like an instruction
    payment_id: String(required=True)
```

### ✅ Correct

```python
@domain.event(part_of="Order")
class OrderPlaced:  # Past-tense - describes what happened
    order_id: String(required=True, identifier=True)
```

```python
@domain.event(part_of="Payment")
class PaymentProcessed:  # Past-tense - this already occurred
    payment_id: String(required=True, identifier=True)
```

**Why it matters:** Events represent facts that have occurred, not instructions to be executed. Imperative names suggest commands, which are conceptually different from events.

## 2. Not Associating Events with Aggregates

### ❌ Wrong

```python
@domain.event  # Missing part_of parameter!
class OrderPlaced:
    order_id: String(required=True)
```

### ✅ Correct

```python
@domain.event(part_of="Order")  # Always specify which aggregate
class OrderPlaced:
    order_id: String(required=True, identifier=True)
```

**Why it matters:** Events must be associated with aggregates. They are written to aggregate-specific streams and this association is required by Protean.

## 3. Including Entities in Events

### ❌ Wrong

```python
@domain.entity(part_of="Order")
class LineItem:
    product_id: String(required=True)
    quantity: Integer(required=True)

@domain.event(part_of="Order")
class OrderPlaced:
    order_id: String(required=True)
    items = HasMany(LineItem)  # Wrong! Can't include entities
```

### ✅ Correct

```python
@domain.event(part_of="Order")
class OrderPlaced:
    order_id: String(required=True, identifier=True)
    items: List()  # Serialize entity data as dictionaries or simple values
    # Or use value objects instead of entities
```

**Why it matters:** Events are DTOs (Data Transfer Objects). They can only contain simple fields and value objects, not entities or aggregates. Entities have identity and lifecycle - events are immutable facts.

## 4. Including Too Much Data

### ❌ Wrong

```python
@domain.event(part_of="Order")
class OrderPlaced:
    order_id: String(required=True)
    # Including entire customer profile when only ID is needed
    customer_name: String(required=True)
    customer_email: String(required=True)
    customer_phone: String()
    customer_address: String()
    customer_birth_date: Date()
    customer_preferences: Dict()
    # ... 20 more customer fields
```

### ✅ Correct

```python
@domain.event(part_of="Order")
class OrderPlaced:
    order_id: String(required=True, identifier=True)
    customer_id: String(required=True)  # Just the ID
    total = ValueObject(Money, required=True)
    placed_at: DateTime(required=True)
    # Only what's necessary to understand what happened
```

**Why it matters:** Events should be lightweight and focused. Include only data necessary to describe the change. Consumers can fetch additional details if needed.

## 5. Making Events Mutable

### ❌ Wrong

```python
event = OrderPlaced(order_id="123", customer_id="456")
# Trying to modify event after creation
event.order_id = "789"  # Wrong! Events are immutable
```

### ✅ Correct

```python
event = OrderPlaced(order_id="123", customer_id="456")
# Events are immutable - cannot be changed
# If you need different data, create a new event
```

**Why it matters:** Events are immutable facts representing what happened in the past. They cannot be changed. This immutability is enforced by Protean.

## 6. Not Versioning Events

### ❌ Wrong

```python
@domain.event(part_of="Order")
class OrderPlaced:
    # Missing __version__ attribute
    order_id: String(required=True)
    customer_id: String(required=True)
```

### ✅ Correct

```python
@domain.event(part_of="Order")
class OrderPlaced:
    __version__ = 1  # Always include version from the start

    order_id: String(required=True, identifier=True)
    customer_id: String(required=True)
```

**Why it matters:** Events are long-lived and stored permanently. Versioning from day one enables schema evolution without breaking consumers.

## 7. Raising Events Before State Changes

### ❌ Wrong

```python
@domain.aggregate
class Order:
    status: String(default="draft")

    def place(self):
        # Wrong: Raising event before state change
        self.raise_(OrderPlaced(
            order_id=self.order_id,
            customer_id=self.customer_id
        ))

        self.status = "placed"  # State change after event
```

### ✅ Correct

```python
@domain.aggregate
class Order:
    status: String(default="draft")

    def place(self):
        # Change state first
        self.status = "placed"

        # Then raise event
        self.raise_(OrderPlaced(
            order_id=self.order_id,
            customer_id=self.customer_id,
            placed_at=datetime.now(timezone.utc)
        ))
```

**Why it matters:** Events describe what happened. The state change must occur first, then the event records that it happened.

## 8. Raising Events for Failed Operations

### ❌ Wrong

```python
@domain.aggregate
class Order:
    def place(self):
        if self.status != "draft":
            # Wrong: Raising event for failure
            self.raise_(OrderPlacementFailed(
                order_id=self.order_id,
                reason="Order already placed"
            ))
            raise ValueError("Order already placed")

        self.status = "placed"
        self.raise_(OrderPlaced(...))
```

### ✅ Correct

```python
@domain.aggregate
class Order:
    def place(self):
        if self.status != "draft":
            # Just raise exception - no event for failures
            raise ValueError("Order already placed")

        self.status = "placed"
        # Only raise event on success
        self.raise_(OrderPlaced(
            order_id=self.order_id,
            customer_id=self.customer_id,
            placed_at=datetime.now(timezone.utc)
        ))
```

**Why it matters:** Events represent successful state changes. Validation failures and errors should not produce events - they prevent state changes from occurring.

## 9. Using Events for Queries

### ❌ Wrong

```python
@domain.aggregate
class Order:
    def get_total(self):
        # Wrong: Raising event in query method
        self.raise_(OrderTotalQueried(order_id=self.order_id))
        return self.total
```

### ✅ Correct

```python
@domain.aggregate
class Order:
    def get_total(self):
        # Query methods don't raise events - no state change
        return self.total
```

**Why it matters:** Events indicate state changes. Query operations that only read data should not raise events.

## 10. Forgetting Identifiers

### ❌ Wrong

```python
@domain.event(part_of="Order")
class OrderPlaced:
    __version__ = 1

    # Missing identifier=True on order_id
    order_id: String(required=True)
    customer_id: String(required=True)
```

### ✅ Correct

```python
@domain.event(part_of="Order")
class OrderPlaced:
    __version__ = 1

    order_id: String(required=True, identifier=True)  # Mark as identifier
    customer_id: String(required=True)
```

**Why it matters:** The primary identifier field should be marked with `identifier=True` to indicate which field uniquely identifies the aggregate instance this event relates to.

## 11. Missing Timestamps

### ❌ Wrong

```python
@domain.event(part_of="Order")
class OrderPlaced:
    __version__ = 1

    order_id: String(required=True, identifier=True)
    customer_id: String(required=True)
    # Missing timestamp!
```

### ✅ Correct

```python
@domain.event(part_of="Order")
class OrderPlaced:
    __version__ = 1

    order_id: String(required=True, identifier=True)
    customer_id: String(required=True)
    placed_at: DateTime(required=True)  # When did this happen?
```

**Why it matters:** Events represent things that happened at a specific point in time. Always include a timestamp indicating when the event occurred.

## 12. Generic Event Names

### ❌ Wrong

```python
@domain.event(part_of="Order")
class OrderUpdated:  # Too generic - what was updated?
    order_id: String(required=True)
    field_name: String()
    new_value: String()
```

```python
@domain.event(part_of="Product")
class StateChanged:  # What state? How did it change?
    product_id: String(required=True)
    new_state: String()
```

### ✅ Correct

```python
@domain.event(part_of="Order")
class OrderShipped:  # Specific - we know exactly what happened
    order_id: String(required=True, identifier=True)
    shipped_at: DateTime(required=True)
    tracking_number: String(required=True)

@domain.event(part_of="Order")
class OrderCancelled:  # Specific state transition
    order_id: String(required=True, identifier=True)
    cancelled_at: DateTime(required=True)
    reason: String(required=True)
```

**Why it matters:** Event names should clearly communicate what happened. Specific names make the domain model explicit and events self-documenting.

## 13. Forgetting Required Fields

### ❌ Wrong

```python
@domain.event(part_of="Order")
class OrderPlaced:
    __version__ = 1

    order_id: String()  # Should be required!
    customer_id: String()  # Should be required!
```

### ✅ Correct

```python
@domain.event(part_of="Order")
class OrderPlaced:
    __version__ = 1

    order_id: String(required=True, identifier=True)
    customer_id: String(required=True)
    placed_at: DateTime(required=True)
```

**Why it matters:** Critical event fields should be marked as required. Events should always have complete, valid data.

## Summary Checklist

When creating events, ensure:

- [ ] Event name is past-tense (OrderPlaced, not PlaceOrder)
- [ ] Event specifies `part_of` parameter
- [ ] Event only contains simple fields and value objects (no entities)
- [ ] Event includes only necessary data
- [ ] Event is immutable (no modification after creation)
- [ ] Event has `__version__` attribute
- [ ] Events are raised AFTER state changes
- [ ] Events are only raised on success (not for failures)
- [ ] Query methods don't raise events
- [ ] Primary identifier marked with `identifier=True`
- [ ] Event includes timestamp of when it occurred
- [ ] Event name is specific and descriptive
- [ ] Required fields are marked as `required=True`

## Related

- [Delta Events](./delta-events.md) - Proper event structure
- [Raising Events](./raising-events.md) - Correct event emission patterns
- [Event Versioning](./event-versioning.md) - Version management
