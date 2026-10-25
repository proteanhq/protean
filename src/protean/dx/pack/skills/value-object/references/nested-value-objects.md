# Nested Value Objects

A value object can hold other value objects through `ValueObject` fields, several levels deep. Each level stays immutable.

## Code

The complete implementation is in [assets/value_object_nested.py](../assets/value_object_nested.py).

## Walkthrough

### Simple Nesting

```python
from decimal import Decimal as D

from protean.exceptions import IncorrectUsageError, ValidationError


@domain.value_object
class Coordinates:
    """Geographic coordinates value object."""
    latitude: Float(required=True, min_value=-90.0, max_value=90.0)
    longitude: Float(required=True, min_value=-180.0, max_value=180.0)


@domain.value_object
class Address:
    """Address containing nested Coordinates."""
    street: String(required=True, max_length=100)
    city: String(required=True, max_length=50)
    state: String(required=True, max_length=50)
    postal_code: String(required=True, max_length=20)
    country: String(required=True, max_length=50)
    coordinates = ValueObject(Coordinates)  # Nested value object
```

### Multiple Nesting Levels

```python
@domain.value_object
class ContactInfo:
    """Contact information with multiple levels of nesting."""
    email: String(required=True, max_length=254)
    phone: String(required=True, max_length=20)
    address = ValueObject(Address)  # Address contains Coordinates
```

### Multiple Nested Value Objects of Same Type

```python
@domain.value_object
class Money:
    currency: String(max_length=3, required=True)
    amount: Decimal(precision=19, scale=4, required=True)


@domain.value_object
class PriceWithTax:
    """Price breakdown with multiple Money instances."""
    base_price = ValueObject(Money, required=True)
    tax_amount = ValueObject(Money, required=True)
    total_price = ValueObject(Money, required=True)
```

Each field gives the one `Money` type its own meaning. Nothing in `PriceWithTax` checks that the three amounts share a currency. That check needs an `@invariant.post`.

## Initialization Patterns

### Do Not Flatten Into a Value Object

A value object's constructor accepts only its own fields. Flattened keyword arguments such as `coordinates_latitude=` fail:

```python
try:
    Address(
        street="456 Market Street",
        city="San Francisco",
        state="CA",
        postal_code="94102",
        country="USA",
        coordinates_latitude=37.7749,
        coordinates_longitude=-122.4194
    )
except ValidationError as exc:
    print(exc.messages)  # coordinates_latitude: Extra inputs are not permitted
```

An aggregate or entity accepts one level of flattening for a value object field it holds directly (`Customer(shipping_address_city="Boston", ...)`). Nothing deeper works, so build nested value objects as objects at every level.

A `ValueObject` field also takes a plain dict of the inner value object's fields, at any depth: `coordinates={"latitude": 40.7128, "longitude": -74.0060}`. Protean builds the value object from the dict and validates it the same way, so a dict with a wrong or missing key raises `ValidationError`.

### Deep Nesting

```python
# Three levels: ContactInfo → Address → Coordinates
contact = ContactInfo(
    email="john@example.com",
    phone="+1-555-0123",
    address=Address(
        street="789 Main St",
        city="Boston",
        state="MA",
        postal_code="02101",
        country="USA",
        coordinates=Coordinates(latitude=42.3601, longitude=-71.0589),
    ),
)
```

## Common Patterns

### Money with Breakdown

This example reuses the `Money` value object defined above.

```python
@domain.value_object
class InvoiceTotal:
    """Invoice total with tax breakdown."""
    subtotal = ValueObject(Money, required=True)
    tax = ValueObject(Money, required=True)
    shipping = ValueObject(Money, required=True)
    total = ValueObject(Money, required=True)

    @invariant.post
    def total_must_match_components(self):
        """Ensure total equals subtotal + tax + shipping."""
        expected_total = (
            self.subtotal.amount +
            self.tax.amount +
            self.shipping.amount
        )

        if self.total.amount != expected_total:
            raise ValidationError(
                {"total": ["Total doesn't match sum of components"]}
            )
```

### Name with Parts

```python
@domain.value_object
class PersonName:
    """Name broken into components."""
    first_name: String(required=True, max_length=50)
    middle_name: String(max_length=50)
    last_name: String(required=True, max_length=50)
    suffix: String(max_length=10)  # Jr, Sr, III, etc.

    @property
    def full_name(self) -> str:
        parts = [self.first_name]
        if self.middle_name:
            parts.append(self.middle_name)
        parts.append(self.last_name)
        if self.suffix:
            parts.append(self.suffix)
        return " ".join(parts)


@domain.value_object
class ContactDetails:
    """Contact with structured name."""
    name = ValueObject(PersonName, required=True)
    email: String(required=True, max_length=254)
    phone: String(max_length=20)
```

## Using Nested Value Objects in Aggregates

```python
@domain.aggregate
class Customer:
    """Customer with nested contact information."""
    customer_id: String(required=True, max_length=50, identifier=True)
    name = ValueObject(PersonName, required=True)
    contact = ValueObject(ContactDetails, required=True)
    shipping_address = ValueObject(Address)
    billing_address = ValueObject(Address)
```

Access patterns:
```python
domain.init(traverse=False)

with domain.domain_context():
    customer = Customer(
        customer_id="CUST-001",
        name=PersonName(first_name="John", last_name="Smith"),
        contact=ContactDetails(
            name=PersonName(first_name="John", last_name="Smith"),
            email="john@example.com",
        ),
        shipping_address=Address(
            street="123 Main St",
            city="Boston",
            state="MA",
            postal_code="02101",
            country="USA",
            coordinates=Coordinates(latitude=42.36, longitude=-71.06),
        ),
    )

# Access nested attributes
print(customer.name.full_name)
print(customer.contact.email)
print(customer.shipping_address.city)
print(customer.shipping_address.coordinates.latitude)
```

## Immutability in Nested Structures

Immutability cascades through all levels:

```python
address = Address(
    street="123 Main St",
    city="Boston",
    state="MA",
    postal_code="02101",
    country="USA",
    coordinates=Coordinates(latitude=42.36, longitude=-71.06)
)

# Cannot modify nested value object
try:
    address.coordinates.latitude = 50.0
except IncorrectUsageError:
    print("Nested value objects are immutable")

# Cannot modify value object itself
try:
    address.city = "New York"
except IncorrectUsageError:
    print("Value objects are immutable")

# To "change", replace entire value object
new_address = Address(
    street="456 Oak Ave",
    city="New York",
    state="NY",
    postal_code="10001",
    country="USA",
    coordinates=Coordinates(latitude=40.71, longitude=-74.01)
)
with domain.domain_context():
    customer.shipping_address = new_address  # This works
```

## Common Mistakes

**Breaking encapsulation** ❌
```python
# fragment
# Reaching too deep into nested structure
if customer.contact.address.coordinates.latitude > 40:
    # Better: Add method to appropriate level
```

## Related

- [Value Objects in Aggregates](./in-aggregates.md): Using nested VOs in aggregates
- [Value Objects with Methods](./with-methods.md): Adding behavior
- [Equality and Immutability](./equality-and-immutability.md): Core concepts
- [Anti-patterns](./anti-patterns.md): What to avoid
