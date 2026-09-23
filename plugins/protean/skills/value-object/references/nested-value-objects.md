# Nested Value Objects

Value objects can contain other value objects, allowing you to build complex domain concepts through composition. This powerful pattern lets you create rich, expressive domain models while maintaining immutability and encapsulation.

## Overview

Use nested value objects when:
- A complex concept is composed of simpler concepts
- You want to reuse value objects across different contexts
- Domain concepts naturally decompose into smaller pieces
- You need to model hierarchical structures

## Code

The complete implementation is in [assets/value_object_nested.py](../assets/value_object_nested.py).

Key highlights:
- Value objects can contain ValueObject fields
- Nesting can be multiple levels deep
- Immutability cascades through nested structures
- Can initialize nested VOs by attributes or objects

## Walkthrough

### Simple Nesting

```python
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

Benefits:
- Coordinates can be reused in other contexts (Store location, Warehouse, etc.)
- Address is complete with geographic data
- Each value object has focused responsibility
- Clean separation of concerns

### Multiple Nesting Levels

```python
@domain.value_object
class ContactInfo:
    """Contact information with multiple levels of nesting."""
    email: String(required=True, max_length=254)
    phone: String(required=True, max_length=20)
    address = ValueObject(Address)  # Address contains Coordinates
```

Three levels:
1. ContactInfo (top level)
2. Address (nested in ContactInfo)
3. Coordinates (nested in Address)

### Multiple Nested Value Objects of Same Type

```python
@domain.value_object
class Money:
    currency: String(max_length=3, required=True)
    amount: Float(required=True)


@domain.value_object
class PriceWithTax:
    """Price breakdown with multiple Money instances."""
    base_price = ValueObject(Money, required=True)
    tax_amount = ValueObject(Money, required=True)
    total_price = ValueObject(Money, required=True)
```

This pattern:
- Uses the same value object type multiple times
- Each instance has a specific meaning
- Ensures currency consistency across all amounts
- Makes price breakdown explicit and type-safe

## Initialization Patterns

### Initialize with Complete Objects

```python
# Create nested value objects first
coords = Coordinates(latitude=40.7128, longitude=-74.0060)
address = Address(
    street="123 Broadway",
    city="New York",
    state="NY",
    postal_code="10012",
    country="USA",
    coordinates=coords
)
```

### Initialize by Attributes

```python
# Initialize nested VO by flattening attributes
address = Address(
    street="456 Market Street",
    city="San Francisco",
    state="CA",
    postal_code="94102",
    country="USA",
    coordinates_latitude=37.7749,
    coordinates_longitude=-122.4194
)
```

The attribute naming pattern:
- `{field_name}_{nested_field_name}`
- `coordinates_latitude` → `coordinates` field, `latitude` attribute
- Works at any nesting depth

### Deep Nesting with Attributes

```python
# Three levels: ContactInfo → Address → Coordinates
contact = ContactInfo(
    email="john@example.com",
    phone="+1-555-0123",
    address_street="789 Main St",
    address_city="Boston",
    address_state="MA",
    address_postal_code="02101",
    address_country="USA",
    address_coordinates_latitude=42.3601,
    address_coordinates_longitude=-71.0589
)
```

## Common Patterns

### Geographic Data

```python
@domain.value_object
class Coordinates:
    latitude: Float(required=True)
    longitude: Float(required=True)


@domain.value_object
class Location:
    """Location with name and coordinates."""
    name: String(required=True, max_length=100)
    coordinates = ValueObject(Coordinates, required=True)

    @property
    def description(self) -> str:
        return f"{self.name} ({self.coordinates.latitude}, {self.coordinates.longitude})"
```

### Money with Breakdown

```python
@domain.value_object
class Money:
    currency: String(max_length=3, required=True)
    amount: Float(required=True)


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

        if abs(self.total.amount - expected_total) > 0.01:
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

### Address with Components

```python
@domain.value_object
class StreetAddress:
    """Street address component."""
    street_number: String(required=True, max_length=10)
    street_name: String(required=True, max_length=100)
    unit_number: String(max_length=10)

    @property
    def full_street(self) -> str:
        parts = [self.street_number, self.street_name]
        if self.unit_number:
            parts.append(f"Unit {self.unit_number}")
        return " ".join(parts)


@domain.value_object
class PostalAddress:
    """Complete postal address."""
    street_address = ValueObject(StreetAddress, required=True)
    city: String(required=True, max_length=50)
    state: String(required=True, max_length=50)
    postal_code: String(required=True, max_length=20)
    country: String(required=True, max_length=50)
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
customer = Customer(...)

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
address.coordinates.latitude = 50.0  # Raises IncorrectUsageError

# Cannot modify value object itself
address.city = "New York"  # Raises IncorrectUsageError

# To "change", replace entire value object
new_address = Address(
    street="456 Oak Ave",
    city="New York",
    state="NY",
    postal_code="10001",
    country="USA",
    coordinates=Coordinates(latitude=40.71, longitude=-74.01)
)
customer.shipping_address = new_address  # This works
```

## Testing Nested Value Objects

```python
def test_nested_value_object_creation():
    coords = Coordinates(latitude=40.7128, longitude=-74.0060)
    address = Address(
        street="123 Broadway",
        city="New York",
        state="NY",
        postal_code="10012",
        country="USA",
        coordinates=coords
    )

    assert address.coordinates.latitude == 40.7128
    assert address.coordinates.longitude == -74.0060

def test_nested_value_object_by_attributes():
    address = Address(
        street="123 Broadway",
        city="New York",
        state="NY",
        postal_code="10012",
        country="USA",
        coordinates_latitude=40.7128,
        coordinates_longitude=-74.0060
    )

    assert address.coordinates.latitude == 40.7128
    assert address.coordinates.longitude == -74.0060

def test_nested_value_object_immutability():
    address = Address(
        street="123 Broadway",
        city="New York",
        state="NY",
        postal_code="10012",
        country="USA",
        coordinates=Coordinates(latitude=40.7128, longitude=-74.0060)
    )

    with pytest.raises(IncorrectUsageError):
        address.coordinates.latitude = 50.0
```

## Best Practices

1. **Reuse value objects** - Same VO can be nested in multiple contexts
2. **Keep nesting reasonable** - Avoid more than 3-4 levels deep
3. **Name fields clearly** - Field name should indicate what it contains
4. **Document composition** - Explain why VOs are nested
5. **Test initialization patterns** - Both object and attribute initialization
6. **Validate relationships** - Use invariants for cross-VO rules
7. **Provide computed properties** - For derived values from nested data

## Common Mistakes

**Over-nesting** ❌
```python
# Too many levels - hard to work with
Customer → Profile → Contact → Address → StreetAddress → Unit → Floor
```

**Breaking encapsulation** ❌
```python
# Reaching too deep into nested structure
if customer.contact.address.coordinates.latitude > 40:
    # Better: Add method to appropriate level
```

**Forgetting immutability** ❌
```python
# Trying to modify nested VO
customer.address.coordinates.latitude = 50.0  # Won't work!
```

## Related

- [Value Objects in Aggregates](./in-aggregates.md) - Using nested VOs in aggregates
- [Value Objects with Methods](./with-methods.md) - Adding behavior
- [Equality and Immutability](./equality-and-immutability.md) - Core concepts
- [Anti-patterns](./anti-patterns.md) - What to avoid
