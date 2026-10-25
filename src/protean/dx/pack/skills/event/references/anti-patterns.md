# Event Anti-Patterns

The examples share this setup. It defines the aggregates the events belong to and the `Money` value object:

```python
from datetime import datetime, timezone

@domain.value_object
class Money:
    amount: Decimal(precision=19, scale=4, required=True)
    currency: String(max_length=3, default="USD")

@domain.aggregate
class Order:
    order_id: String(required=True, identifier=True)
    customer_id: String(required=True)
    status: String(default="draft")
    total = ValueObject(Money)

@domain.aggregate
class Payment:
    payment_id: String(required=True, identifier=True)

@domain.aggregate
class Product:
    product_id: String(required=True, identifier=True)
```

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
# fragment
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

**Why it matters:** Protean writes an event to its aggregate's stream. Decorating an event with neither `part_of` nor `stream_category` raises `IncorrectUsageError` at once: ``Event `OrderPlaced` needs to be associated with an aggregate or a stream``.

## 3. Including Entities in Events

### ❌ Wrong

```python
# fragment
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

**Why it matters:** Events are DTOs (Data Transfer Objects). They can only contain simple fields and value objects, not entities or aggregates. Entities have identity and a lifecycle, and events are immutable facts.

## 4. Not Versioning Events

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

**Why it matters:** `__version__` defaults to `1`, so both classes produce the event type `OrderPlaced.v1`. Writing it out keeps the version visible in the class for the day you add v2 and its upcaster.

## 5. Raising Events Before State Changes

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
    order_id: String(required=True, identifier=True)
    customer_id: String(required=True)
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

This rule is for aggregates that store their state. An event-sourced aggregate works the other way. The business method raises the event, and an `@apply` method changes the state. See the `event-sourced-aggregate` skill.

## 6. Raising Events for Failed Operations

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

**Why it matters:** Events represent successful state changes. Validation failures and errors prevent the state change, so they produce no event.

## 7. Using Events for Queries

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

## 8. Forgetting Identifiers

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

## 9. Missing Timestamps

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

**Why it matters:** Protean stamps every event with the time it was raised, in `_metadata.headers.time`. Add a field such as `placed_at` when consumers need the time of the business change in the payload.

## 10. Generic Event Names

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

## 11. Forgetting Required Fields

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

## Related

- [Delta Events](./delta-events.md): Proper event structure
- [Raising Events](./raising-events.md): Correct event emission patterns
- [Event Versioning](./event-versioning.md): Version management
