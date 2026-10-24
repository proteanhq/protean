# Aggregates with Value Objects

Aggregates use value objects to represent complex, immutable data types that don't have identity. Two value objects with the same attributes are equal.

## Code

The complete implementation is in [assets/aggregate_with_value_object.py](../assets/aggregate_with_value_object.py).

## Walkthrough

### Defining Value Objects

```python
@domain.value_object
class Money:
    amount: Decimal(precision=19, scale=4, required=True)
    currency: String(max_length=3, default="USD")

    def add(self, other: "Money") -> "Money":
        if self.currency != other.currency:
            raise ValueError("Cannot add different currencies")
        return Money(
            amount=self.amount + other.amount,
            currency=self.currency
        )

    def multiply(self, factor: int) -> "Money":
        return Money(amount=self.amount * factor, currency=self.currency)


@domain.value_object
class Address:
    street: String(required=True, max_length=200)
    city: String(required=True, max_length=100)
    postal_code: String(max_length=20)
    country: String(max_length=100)

    def full_address(self) -> str:
        return f"{self.street}, {self.city} {self.postal_code}, {self.country}"
```

### Using Value Objects in Aggregates

```python
@domain.aggregate
class Order:
    customer_id: Identifier(required=True)
    lines = HasMany("OrderLine")

    # Value object fields
    shipping_address = ValueObject(Address)
    billing_address = ValueObject(Address)
```

The `ValueObject` field type accepts the value object class.

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

Creating instances needs an initialized domain and an active domain context:

```python
domain.init(traverse=False)
```

### Working with Value Objects

**Creating value objects:**

```python
with domain.domain_context():
    price = Money(amount="29.99", currency="USD")
    address = Address(
        street="123 Main St",
        city="San Francisco",
        postal_code="94102",
        country="USA"
    )
```

**Using value objects in aggregates:**

```python
with domain.domain_context():
    order = Order(
        customer_id="C123",
        shipping_address=address,
        billing_address=address  # Can reuse - no identity issues
    )
```

**Accessing value object attributes:**

```python
with domain.domain_context():
    # Direct access
    order.shipping_address.city  # "San Francisco"

    # Through behavior
    full_addr = order.shipping_address.full_address()
```

**Value object immutability:**

```python
with domain.domain_context():
    # This creates a NEW Money object
    new_price = price.multiply(2)
    print(price.amount)      # Still 29.99
    print(new_price.amount)  # 59.98
```

## Flattening Value Object Attributes

When persisted, value object attributes are flattened into the parent:

```python
# For shipping_address = ValueObject(Address) on Order,
# the database/storage holds:
# - shipping_address_street
# - shipping_address_city
# - shipping_address_postal_code
# - shipping_address_country
```

You can access these flattened attributes directly:

```python
with domain.domain_context():
    order.shipping_address_city  # "San Francisco"
```

## Common Patterns

### Calculated Properties Using Value Objects

Add a property to the `Order` aggregate that folds its lines into one `Money`:

```python
# fragment
@property
def order_total(self) -> Money:
    total = Money(amount=0, currency="USD")
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
    # For several phones, use List(content_type=ValueObject(Phone)),
    # or an entity when each phone needs an identity
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

Pass the inner value object as an object, not as flattened keyword arguments:

```python
domain.init(traverse=False)

with domain.domain_context():
    address = Address(
        street="123 Main St",
        city="San Francisco",
        location=Coordinates(latitude=37.7749, longitude=-122.4194),
    )
```

## Related

- [Aggregates with Entities](./with-entities.md)
- [value-object](../../value-object/SKILL.md): Detailed value object documentation
- [Anti-patterns](./anti-patterns.md): Common mistakes with value objects
