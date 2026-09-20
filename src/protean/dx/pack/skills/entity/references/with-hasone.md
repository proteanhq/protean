# Entity with HasOne Relationships

Entities can have one-to-one relationships with other entities using the `HasOne` field. This pattern is useful when you need to model optional or required related information that logically belongs to the entity but is complex enough to warrant its own entity.

## Overview

A `HasOne` relationship creates a one-to-one association between two entities within the same aggregate. The parent entity "has one" instance of the child entity.

### When to Use HasOne

- An entity needs optional detailed information (e.g., Order → ShippingInfo)
- The related data is complex with multiple fields
- The relationship is one-to-one
- Both entities belong to the same aggregate
- You want to model optional components (can be None)

### When NOT to Use HasOne

- The relationship is one-to-many (use `HasMany` instead)
- The related data is simple (use a `ValueObject` instead)
- The related data should be embedded (use nested value object fields)
- You need many-to-many relationships (not supported within aggregates)

## Code

The complete implementation is in [assets/entity_with_hasone.py](../assets/entity_with_hasone.py).

Key highlights:
- `ShippingInfo` entity is associated with `Order` aggregate via one-to-one relationship
- Order defines `shipping_info = HasOne("ShippingInfo")`
- ShippingInfo gets automatic reference back to Order
- HasOne fields can be None (optional relationship)
- Business logic can validate the related entity

## Walkthrough

### The Aggregate

```python
@domain.aggregate
class Order:
    customer_id: String(required=True, max_length=50)
    status: String(max_length=20, default="pending")

    # One-to-many: order has many line items
    line_items = HasMany("LineItem")

    # One-to-one: order has one shipping info
    shipping_info = HasOne("ShippingInfo")
```

The Order aggregate defines two types of relationships:
- `line_items`: HasMany relationship (one-to-many)
- `shipping_info`: HasOne relationship (one-to-one)

### The HasOne Entity

```python
@domain.entity(part_of="Order")
class ShippingInfo:
    address: String(required=True, max_length=500)
    city: String(required=True, max_length=100)
    state: String(max_length=50)
    postal_code: String(required=True, max_length=20)
    country: String(max_length=50, default="USA")
    phone: String(max_length=20)

    # Automatic reference back to parent
    order = Reference(Order)
```

The ShippingInfo entity:
- Must specify `part_of=Order` to associate with the aggregate
- Gets an automatic `order` reference field pointing back to the parent
- Gets an automatic `order_id` shadow field for the parent's ID
- Can have its own business logic and validation

### Setting HasOne Relationships

```python
# Create the aggregate
order = Order(customer_id="CUST-12345")

# Create the related entity
shipping = ShippingInfo(
    address="123 Main Street",
    city="San Francisco",
    state="CA",
    postal_code="94102",
    country="USA",
)

# Set the HasOne relationship
order.shipping_info = shipping
```

Unlike HasMany where you use `add_*` methods, HasOne relationships are set directly via assignment.

### Accessing HasOne Relationships

```python
# Access the related entity
if order.shipping_info:
    print(f"Shipping to: {order.shipping_info.city}")
    print(f"Address: {order.shipping_info.full_address}")
```

HasOne relationships can be None if not set, so always check before accessing.

### Bidirectional Navigation

```python
# Access parent from child
shipping = order.shipping_info
parent_order = shipping.order  # Navigate back to Order
order_id = shipping.order_id   # Get parent's ID
```

The automatic reference field enables navigation from child back to parent.

### Business Logic with HasOne

```python
@domain.aggregate
class Order:
    # ... fields ...

    @property
    def is_shippable(self) -> bool:
        """Check if order can be shipped."""
        return self.shipping_info is not None and len(self.line_items) > 0

    def validate_for_shipment(self):
        """Validate order is ready for shipment."""
        if self.shipping_info is None:
            raise ValueError("Order must have shipping information")
        if not self.shipping_info.is_valid:
            raise ValueError("Shipping address is incomplete")
```

The aggregate can validate the HasOne entity and enforce business rules.

## Common Patterns

### Optional HasOne

```python
@domain.aggregate
class Order:
    shipping_info = HasOne("ShippingInfo")  # Optional - can be None

    def ship(self):
        if self.shipping_info is None:
            raise ValueError("Cannot ship without shipping info")
```

HasOne relationships are optional by default. Check for None before using.

### Required HasOne (via validation)

```python
@domain.aggregate
class Order:
    shipping_info = HasOne("ShippingInfo")

    def place(self):
        if not self.shipping_info:
            raise ValueError("Shipping info required to place order")
        self.status = "placed"
```

While you can't make HasOne required at the field level, you can enforce it in business logic.

### HasOne with Computed Properties

```python
@domain.entity(part_of="Order")
class ShippingInfo:
    address: String(required=True)
    city: String(required=True)
    state: String()
    postal_code: String(required=True)
    country: String(default="USA")

    @property
    def full_address(self) -> str:
        """Get formatted full address."""
        parts = [self.address, self.city]
        if self.state:
            parts.append(self.state)
        parts.extend([self.postal_code, self.country])
        return ", ".join(parts)
```

Entities in HasOne relationships can have their own methods and properties.

## Testing

See [assets/entity_with_hasone.py](../assets/entity_with_hasone.py) for runnable examples.

To test HasOne relationships:

```python
def test_hasone_relationship():
    order = Order(customer_id="C123")
    shipping = ShippingInfo(
        address="123 Main St",
        city="NYC",
        postal_code="10001",
        country="USA"
    )
    order.shipping_info = shipping

    # Test relationship is set
    assert order.shipping_info is not None
    assert order.shipping_info.city == "NYC"

    # Test bidirectional reference
    assert shipping.order == order
    assert shipping.order_id == order.id
```

## Related

- [HasMany relationships](./with-hasmany.md) - One-to-many entity relationships
- [Nested entities](./nested-entities.md) - Entities containing other entities
- [Value objects](../../value-object/SKILL.md) - When to use value objects instead
