# Events with Value Objects

Events can contain value objects to represent complex immutable data structures. This enables events to carry rich, structured information while maintaining immutability and type safety.

## Overview

Value objects are immutable complex types that represent domain concepts with multiple attributes (Money, Address, Coordinates, etc.). Including value objects in events provides:

- **Type safety** - Structured data with validation
- **Immutability** - Value objects are immutable, perfect for events
- **Domain modeling** - Express domain concepts clearly
- **Reusability** - Same value objects used across events and aggregates

## Code

The complete implementation is in [assets/event_with_value_object.py](../assets/event_with_value_object.py).

Key highlights:
- Value objects encapsulate complex immutable data
- Events use `ValueObject()` field to reference them
- Same value objects can be shared across events and aggregates
- Type safety and validation built-in

## Common Value Objects in Events

### Money

The most common value object in business events:

```python
@domain.value_object
class Money:
    amount: Float(required=True)
    currency: String(max_length=3, default="USD")

    def add(self, other: "Money") -> "Money":
        if self.currency != other.currency:
            raise ValueError("Cannot add different currencies")
        return Money(amount=self.amount + other.amount, currency=self.currency)

@domain.event(part_of="Order")
class OrderPlaced:
    __version__ = 1

    order_id: String(required=True, identifier=True)
    customer_id: String(required=True)
    total = ValueObject(Money, required=True)
    placed_at: DateTime(required=True)
```

### Address

For shipping, billing, and location information:

```python
@domain.value_object
class Address:
    street: String(required=True, max_length=200)
    city: String(required=True, max_length=100)
    state: String(max_length=50)
    postal_code: String(required=True, max_length=20)
    country: String(required=True, max_length=50)

@domain.event(part_of="Order")
class OrderShipped:
    __version__ = 1

    order_id: String(required=True, identifier=True)
    shipped_at: DateTime(required=True)
    shipping_address = ValueObject(Address, required=True)
    tracking_number: String(required=True)
```

### Coordinates

For geolocation events:

```python
@domain.value_object
class Coordinates:
    latitude: Float(required=True, min_value=-90.0, max_value=90.0)
    longitude: Float(required=True, min_value=-180.0, max_value=180.0)

@domain.event(part_of="Shipment")
class ShipmentLocationUpdated:
    __version__ = 1

    shipment_id: String(required=True, identifier=True)
    location = ValueObject(Coordinates, required=True)
    updated_at: DateTime(required=True)
```

## Multiple Value Objects in One Event

Events can contain multiple value objects:

```python
@domain.value_object
class Money:
    amount: Float(required=True)
    currency: String(max_length=3, default="USD")

@domain.value_object
class Address:
    street: String(required=True, max_length=200)
    city: String(required=True, max_length=100)
    postal_code: String(required=True, max_length=20)
    country: String(required=True, max_length=50)

@domain.event(part_of="Order")
class OrderPlaced:
    __version__ = 1

    order_id: String(required=True, identifier=True)
    customer_id: String(required=True)

    # Multiple value objects
    total = ValueObject(Money, required=True)
    shipping_address = ValueObject(Address, required=True)
    billing_address = ValueObject(Address)

    placed_at: DateTime(required=True)
```

## Nested Value Objects

Value objects can contain other value objects:

```python
@domain.value_object
class Money:
    amount: Float(required=True)
    currency: String(max_length=3, default="USD")

@domain.value_object
class PriceBreakdown:
    subtotal = ValueObject(Money, required=True)
    tax = ValueObject(Money, required=True)
    shipping = ValueObject(Money, required=True)
    discount = ValueObject(Money)

    @property
    def total(self) -> Money:
        result = Money(
            amount=self.subtotal.amount + self.tax.amount + self.shipping.amount,
            currency=self.subtotal.currency
        )
        if self.discount:
            result = Money(
                amount=result.amount - self.discount.amount,
                currency=result.currency
            )
        return result

@domain.event(part_of="Order")
class OrderPlaced:
    __version__ = 1

    order_id: String(required=True, identifier=True)
    customer_id: String(required=True)
    pricing = ValueObject(PriceBreakdown, required=True)
    placed_at: DateTime(required=True)
```

## Value Objects vs Simple Fields

### When to Use Value Objects

Use value objects when:
- Multiple related attributes form a cohesive concept (Money has amount + currency)
- You need behavior/validation on the data (currency conversion, address validation)
- The concept is reused across multiple events/aggregates
- Type safety and domain clarity are important

### When to Use Simple Fields

Use simple fields when:
- Single primitive value is sufficient
- No related attributes or behavior needed
- Concept is specific to this one event

```python
# Good: Simple field for single value
@domain.event(part_of="User")
class UserEmailChanged:
    user_id: String(required=True, identifier=True)
    new_email: String(required=True)  # Just a string
    changed_at: DateTime(required=True)

# Good: Value object for complex concept
@domain.event(part_of="Order")
class OrderPlaced:
    order_id: String(required=True, identifier=True)
    total = ValueObject(Money, required=True)  # Complex: amount + currency
    placed_at: DateTime(required=True)
```

## Creating Events with Value Objects

When raising events, instantiate value objects:

```python
from datetime import datetime, timezone

@domain.aggregate
class Order:
    order_id: String(required=True, identifier=True)
    customer_id: String(required=True)
    total = ValueObject(Money)
    shipping_address = ValueObject(Address)

    def place(self):
        self.status = "placed"

        # Raise event with value objects
        self.raise_(OrderPlaced(
            order_id=self.order_id,
            customer_id=self.customer_id,
            total=self.total,  # Value object from aggregate
            shipping_address=self.shipping_address,
            placed_at=datetime.now(timezone.utc)
        ))

# Usage
order = Order(
    order_id="ORD-001",
    customer_id="CUST-123",
    total=Money(amount=99.99, currency="USD"),
    shipping_address=Address(
        street="123 Main St",
        city="San Francisco",
        state="CA",
        postal_code="94102",
        country="USA"
    )
)
order.place()
```

## Domain-Specific Value Objects

Create value objects that represent your domain concepts:

### E-Commerce

```python
@domain.value_object
class OrderItem:
    product_id: String(required=True)
    product_name: String(required=True)
    quantity: Integer(required=True, min_value=1)
    unit_price = ValueObject(Money, required=True)

    @property
    def subtotal(self) -> Money:
        return Money(
            amount=self.unit_price.amount * self.quantity,
            currency=self.unit_price.currency
        )

@domain.event(part_of="Order")
class OrderItemAdded:
    __version__ = 1
    order_id: String(required=True, identifier=True)
    item = ValueObject(OrderItem, required=True)
    added_at: DateTime(required=True)
```

### Financial Services

```python
@domain.value_object
class TransactionDetails:
    amount = ValueObject(Money, required=True)
    transaction_type: String(required=True, choices=["debit", "credit"])
    reference_number: String(required=True)
    description: String(max_length=500)

@domain.event(part_of="Account")
class TransactionProcessed:
    __version__ = 1
    account_id: String(required=True, identifier=True)
    transaction = ValueObject(TransactionDetails, required=True)
    processed_at: DateTime(required=True)
    new_balance = ValueObject(Money, required=True)
```

### Healthcare

```python
@domain.value_object
class VitalSigns:
    blood_pressure_systolic: Integer(required=True, min_value=0, max_value=300)
    blood_pressure_diastolic: Integer(required=True, min_value=0, max_value=200)
    heart_rate: Integer(required=True, min_value=0, max_value=300)
    temperature: Float(required=True, min_value=90.0, max_value=110.0)

@domain.event(part_of="Patient")
class VitalSignsRecorded:
    __version__ = 1
    patient_id: String(required=True, identifier=True)
    vitals = ValueObject(VitalSigns, required=True)
    recorded_at: DateTime(required=True)
    recorded_by: String(required=True)
```

## Best Practices

1. **Reuse value objects** - Same value objects across events, aggregates, and commands
2. **Keep value objects immutable** - Never add methods that modify state
3. **Add behavior to value objects** - Validation, calculations, formatting
4. **Use composition** - Value objects can contain other value objects
5. **Document purpose** - Clear docstrings on value objects and their usage

## Related

- [Delta Events](./delta-events.md) - Incremental state changes
- [Fact Events](./fact-events.md) - Complete state snapshots
- `value-object` - Detailed value object patterns
