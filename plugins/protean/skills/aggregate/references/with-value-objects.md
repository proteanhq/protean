# Aggregates with Value Objects

Aggregates use value objects to represent complex, immutable data types that don't have identity. Value objects are defined by their attributes rather than by an identifier.

## Overview

Use value objects when:
- You need to model a concept that is defined by its attributes, not identity
- The object should be immutable
- You want to encapsulate behavior with the data
- Examples: Money, Address, DateRange, Coordinates

## Key Differences: Value Objects vs Entities

| Aspect | Value Object | Entity |
|--------|-------------|--------|
| Identity | No identity, defined by attributes | Has unique identifier |
| Mutability | Immutable | Mutable |
| Equality | Based on all attributes | Based on identifier |
| Lifecycle | No independent lifecycle | Can have independent lifecycle |
| Examples | Money, Address, Phone | LineItem, Comment, Person |

## Code

The complete implementation is in [assets/aggregate_with_value_object.py](../assets/aggregate_with_value_object.py).

Key highlights:
- Value objects defined with `@domain.value_object`
- Used in aggregates via `ValueObject(ClassName)` field
- Value objects can have behavior (methods)
- Value objects can be used in both aggregates and entities
- Value objects are immutable by default

## Walkthrough

### Defining Value Objects

```python
@domain.value_object
class Money:
    amount: Float(required=True)
    currency: String(max_length=3, default="USD")

    def add(self, other: "Money") -> "Money":
        if self.currency != other.currency:
            raise ValueError("Cannot add different currencies")
        return Money(
            amount=self.amount + other.amount,
            currency=self.currency
        )
```

Value objects:
- Encapsulate related data
- Can include business logic (methods)
- Return new instances rather than mutating (immutability)
- Can validate business rules (same currency for addition)

### Using Value Objects in Aggregates

```python
@domain.aggregate
class Order:
    customer_id: String(required=True)

    # Value object fields
    shipping_address = ValueObject(Address)
    billing_address = ValueObject(Address)
```

The `ValueObject` field type accepts the value object class. The aggregate now has complex, structured data with behavior.

### Using Value Objects in Entities

```python
@domain.entity(part_of="Order")
class OrderLine:
    product_name: String(required=True)
    quantity: Integer(required=True)
    unit_price = ValueObject(Money, required=True)

    @property
    def line_total(self) -> Money:
        return self.unit_price.multiply(self.quantity)
```

Entities can also contain value objects, combining identity (entity) with rich data types (value objects).

### Working with Value Objects

**Creating value objects:**

```python
price = Money(amount=29.99, currency="USD")
address = Address(
    street="123 Main St",
    city="San Francisco",
    postal_code="94102",
    country="USA"
)
```

**Using value objects in aggregates:**

```python
order = Order(
    customer_id="C123",
    shipping_address=address,
    billing_address=address  # Can reuse - no identity issues
)
```

**Accessing value object attributes:**

```python
# Direct access
order.shipping_address.city  # "San Francisco"

# Through behavior
full_addr = order.shipping_address.full_address()
```

**Value object immutability:**

```python
# This creates a NEW Money object
new_price = price.multiply(2)
print(price.amount)      # Still 29.99
print(new_price.amount)  # 59.98
```

## Flattening Value Object Attributes

When persisted, value object attributes are flattened into the parent:

```python
@domain.aggregate
class Order:
    shipping_address = ValueObject(Address)

# In database/storage:
# - shipping_address_street
# - shipping_address_city
# - shipping_address_postal_code
# - shipping_address_country
```

You can access these flattened attributes directly:

```python
order.shipping_address_city  # "San Francisco"
```

## Value Objects with Behavior

Value objects shine when they encapsulate both data and behavior:

```python
@domain.value_object
class Money:
    amount: Float(required=True)
    currency: String(required=True, max_length=3)

    def add(self, other: "Money") -> "Money":
        """Add two monetary amounts."""
        if self.currency != other.currency:
            raise ValueError("Currency mismatch")
        return Money(amount=self.amount + other.amount, currency=self.currency)

    def multiply(self, factor: float) -> "Money":
        """Multiply amount by a factor."""
        return Money(amount=self.amount * factor, currency=self.currency)

    def is_positive(self) -> bool:
        """Check if amount is positive."""
        return self.amount > 0

    def __str__(self) -> str:
        return f"{self.amount:.2f} {self.currency}"
```

This encapsulation:
- Keeps money logic with money data
- Makes code more expressive: `total.add(tax)` vs `total + tax`
- Prevents invalid operations (adding different currencies)
- Enables reuse across aggregates

## Common Patterns

### Calculated Properties Using Value Objects

```python
@domain.aggregate
class Order:
    lines = HasMany(OrderLine)

    @property
    def order_total(self) -> Money:
        total = Money(amount=0.0, currency="USD")
        for line in self.lines:
            total = total.add(line.line_total)
        return total
```

### Value Objects in Collections

```python
@domain.value_object
class Phone:
    country_code: String(max_length=5, default="+1")
    number: String(required=True, max_length=15)

@domain.aggregate
class Contact:
    name: String(required=True)
    primary_phone = ValueObject(Phone)
    # For multiple phones, use an entity instead
```

### Nested Value Objects

Value objects can contain other value objects:

```python
@domain.value_object
class Coordinates:
    latitude: Float(required=True)
    longitude: Float(required=True)

@domain.value_object
class Address:
    street: String(required=True)
    city: String(required=True)
    location = ValueObject(Coordinates)
```

## Best Practices

1. **Prefer value objects over entities when possible** - If it doesn't need identity, use a value object
2. **Make value objects immutable** - Always return new instances from methods
3. **Add behavior to value objects** - Don't treat them as simple data holders
4. **Validate in value object constructors** - Ensure value objects are always valid
5. **Use value objects for domain concepts** - Money, Address, DateRange are better than primitives
6. **Keep value objects focused** - Each should represent one cohesive concept

## When NOT to Use Value Objects

Use entities instead when:
- The object needs a unique identifier
- The object has an independent lifecycle
- You need to track the object over time
- The object is mutable by design
- Example: LineItem in an order (has identity, can be modified)

## Related

- [Aggregates with Entities](./with-entities.md)
- [value-object](../../value-object/SKILL.md) - Detailed value object documentation
- [Anti-patterns](./anti-patterns.md) - Common mistakes with value objects
