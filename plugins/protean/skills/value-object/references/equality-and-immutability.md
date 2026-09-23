# Equality and Immutability

Two fundamental characteristics define value objects: they are compared by their attribute values (equality) and they cannot be changed once created (immutability). Understanding these concepts is essential to using value objects correctly.

## Overview

Key concepts:
- **Equality**: Two value objects with same attributes are equal
- **Immutability**: Value objects cannot be modified after creation
- **No Identity**: Value objects have no unique identifier
- **Interchangeability**: Equal value objects can be swapped freely

## Equality

### Value-Based Equality

Value objects are equal when all their attributes match:

```python
@domain.value_object
class Money:
    currency: String(max_length=3, required=True)
    amount: Float(required=True)


# Two instances with same values
m1 = Money(currency="USD", amount=100.0)
m2 = Money(currency="USD", amount=100.0)

# They are equal
assert m1 == m2  # True

# Different values are not equal
m3 = Money(currency="EUR", amount=100.0)
assert m1 == m3  # False
```

This is fundamentally different from entities, where identity matters:

```python
@domain.entity(part_of="Order")
class LineItem:
    product_id: String(required=True)
    quantity: Integer(required=True)

# Two entities with same attributes but different IDs
item1 = LineItem(product_id="PROD-1", quantity=5)
item2 = LineItem(product_id="PROD-1", quantity=5)

# They are NOT equal (different identities)
assert item1 != item2
```

### All Attributes Matter

ALL attributes must match for equality:

```python
@domain.value_object
class Address:
    street: String(required=True)
    city: String(required=True)
    state: String(required=True)
    postal_code: String(required=True)

addr1 = Address(
    street="123 Main St",
    city="Boston",
    state="MA",
    postal_code="02101"
)

addr2 = Address(
    street="123 Main St",
    city="Boston",
    state="MA",
    postal_code="02101"
)

# All attributes match
assert addr1 == addr2  # True

addr3 = Address(
    street="123 Main St",  # Same street
    city="Boston",
    state="MA",
    postal_code="02102"    # Different postal code
)

# One attribute differs
assert addr1 == addr3  # False
```

### Nested Value Objects

Equality cascades through nested value objects:

```python
@domain.value_object
class Coordinates:
    latitude: Float(required=True)
    longitude: Float(required=True)


@domain.value_object
class Location:
    name: String(required=True)
    coordinates = ValueObject(Coordinates)

loc1 = Location(
    name="Office",
    coordinates=Coordinates(latitude=40.7, longitude=-74.0)
)

loc2 = Location(
    name="Office",
    coordinates=Coordinates(latitude=40.7, longitude=-74.0)
)

# Deep equality - nested VOs also compared
assert loc1 == loc2  # True
```

## Immutability

### Cannot Modify After Creation

Value objects cannot be changed once created:

```python
money = Money(currency="USD", amount=100.0)

# This raises IncorrectUsageError
money.currency = "EUR"

# This also raises IncorrectUsageError
money.amount = 200.0
```

### Replace Instead of Modify

To "change" a value object, create a new instance:

```python
# Original value object
order.total = Money(currency="USD", amount=100.0)

# Cannot modify
# order.total.amount = 200.0  # Won't work!

# Replace with new instance
order.total = Money(currency="USD", amount=200.0)
```

### Why Immutability Matters

Immutability provides several benefits:

**1. Thread Safety**
```python
# Value objects can be safely shared between threads
shared_price = Money(currency="USD", amount=50.0)

# Multiple threads can read without locks
# No thread can modify it
```

**2. Predictable Behavior**
```python
def calculate_discount(price: Money, rate: float) -> Money:
    # price parameter won't be modified
    # Safe to use without defensive copying
    return price.multiply(1.0 - rate)

original_price = Money(currency="USD", amount=100.0)
discounted = calculate_discount(original_price, 0.1)

# original_price unchanged
assert original_price.amount == 100.0
```

**3. Safe Caching**
```python
# Value objects can be cached safely
cache = {}

address = Address(...)
cache[address] = compute_expensive_result(address)

# Address can't change, so cache entry remains valid
```

### Methods Return New Instances

Value object methods that "modify" values return NEW instances:

```python
@domain.value_object
class Money:
    currency: String(max_length=3, required=True)
    amount: Float(required=True)

    def add(self, other: "Money") -> "Money":
        # Returns NEW instance
        return Money(
            currency=self.currency,
            amount=self.amount + other.amount
        )

m1 = Money(currency="USD", amount=100.0)
m2 = Money(currency="USD", amount=50.0)

# add() returns new instance
m3 = m1.add(m2)

# Original instances unchanged
assert m1.amount == 100.0
assert m2.amount == 50.0
assert m3.amount == 150.0
```

### Immutability in Aggregates

When value objects are embedded in aggregates, replace them entirely:

```python
@domain.aggregate
class Account:
    balance = ValueObject(Money)

account = Account(balance=Money(currency="USD", amount=1000.0))

# Cannot modify VO attribute
# account.balance.amount = 1500.0  # Won't work!

# Replace entire VO
account.balance = Money(currency="USD", amount=1500.0)

# Or use shadow attributes (only during initialization)
account = Account(balance_currency="USD", balance_amount=1000.0)
```

## No Identity

### Value Objects Have No ID

Unlike entities and aggregates, value objects don't have identity fields:

```python
@domain.value_object
class Money:
    # Cannot use identifier=True
    # id: String(identifier=True)  # Raises IncorrectUsageError

    currency: String(max_length=3, required=True)
    amount: Float(required=True)
```

Trying to add identity fields raises an error:

```python
# This will fail
@domain.value_object
class Address:
    id: Auto()  # Error: Value objects cannot have identity fields
    street: String()
```

### Value Objects Cannot Be Unique

Cannot mark fields as unique:

```python
@domain.value_object
class Email:
    # Cannot use unique=True
    # address: String(unique=True)  # Raises IncorrectUsageError

    address: String(max_length=254, required=True)
```

### Interchangeability

Because value objects have no identity, equal instances are interchangeable:

```python
@domain.aggregate
class Order:
    shipping_address = ValueObject(Address)

# Two equal addresses
addr1 = Address(street="123 Main", city="Boston", ...)
addr2 = Address(street="123 Main", city="Boston", ...)

order = Order(shipping_address=addr1)

# Can swap with equal VO
order.shipping_address = addr2

# No meaningful difference - they're equal
assert addr1 == addr2
```

## Practical Implications

### In Collections

Value objects can be used in sets because equality is well-defined:

```python
addresses = set()
addresses.add(Address(street="123 Main", city="Boston", ...))
addresses.add(Address(street="123 Main", city="Boston", ...))  # Same values

# Set contains only one address (they're equal)
assert len(addresses) == 1
```

### As Dictionary Keys

Value objects can be dictionary keys (with caution):

```python
shipping_costs = {
    Address(...): Money(currency="USD", amount=10.0),
    Address(...): Money(currency="USD", amount=15.0),
}
```

**Note**: Use carefully. If the value object is mutable in practice (against the pattern), dictionary keys can break.

### In Comparisons

```python
@domain.aggregate
class Order:
    shipping_address = ValueObject(Address)
    billing_address = ValueObject(Address)

    def uses_same_address_for_billing(self) -> bool:
        # Equality comparison
        return self.shipping_address == self.billing_address
```

## Testing Equality and Immutability

```python
def test_value_object_equality():
    m1 = Money(currency="USD", amount=100.0)
    m2 = Money(currency="USD", amount=100.0)
    m3 = Money(currency="EUR", amount=100.0)

    # Same values are equal
    assert m1 == m2
    # Different values are not equal
    assert m1 != m3

def test_value_object_immutability():
    money = Money(currency="USD", amount=100.0)

    with pytest.raises(IncorrectUsageError):
        money.currency = "EUR"

    with pytest.raises(IncorrectUsageError):
        money.amount = 200.0

def test_methods_return_new_instances():
    m1 = Money(currency="USD", amount=100.0)
    m2 = Money(currency="USD", amount=50.0)

    m3 = m1.add(m2)

    # New instance created
    assert m3.amount == 150.0
    # Originals unchanged
    assert m1.amount == 100.0
    assert m2.amount == 50.0

def test_nested_value_object_equality():
    loc1 = Location(
        name="Office",
        coordinates=Coordinates(latitude=40.7, longitude=-74.0)
    )
    loc2 = Location(
        name="Office",
        coordinates=Coordinates(latitude=40.7, longitude=-74.0)
    )

    assert loc1 == loc2
```

## Common Mistakes

**Trying to modify value objects** ❌
```python
money.amount = 200  # Won't work!
```

**Expecting identity-based equality** ❌
```python
m1 = Money(currency="USD", amount=100)
m2 = Money(currency="USD", amount=100)

# Wrong assumption: they're different objects
if m1 is not m2:  # True, but misleading
    # They're EQUAL even though not same object
    assert m1 == m2  # True!
```

**Adding identity fields** ❌
```python
@domain.value_object
class Money:
    id: Auto()  # Error! VOs can't have identity
```

**Modifying then expecting changes** ❌
```python
order.total.amount = 200  # Raises error
# Must replace entire VO
order.total = Money(currency="USD", amount=200)
```

## Best Practices

1. **Test equality** - Verify VOs with same values are equal
2. **Test immutability** - Ensure modifications raise errors
3. **Replace, not modify** - Always create new instances
4. **Use in comparisons** - Leverage equality for business logic
5. **Document why immutable** - Help team understand the pattern
6. **No identity fields** - Never add IDs to value objects
7. **Return new from methods** - Never modify self

## Related

- [Value Objects with Methods](./with-methods.md) - Methods that return new instances
- [Value Objects in Aggregates](./in-aggregates.md) - Replacing VOs in aggregates
- [Anti-patterns](./anti-patterns.md) - Common equality/immutability mistakes
