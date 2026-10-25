# Entity with HasOne Relationships

A `HasOne` field links an aggregate or entity to exactly one child entity in the same aggregate. Use it when the related data has its own identity and several fields, such as `Order` and its `ShippingInfo`. Use `HasMany` for a one-to-many link, and a `ValueObject` for simple data with no identity. Many-to-many relationships are not supported within an aggregate.

## Code

The complete implementation is in [assets/entity_with_hasone.py](../assets/entity_with_hasone.py).

## Walkthrough

### The Aggregate

```python
from protean import Domain
from protean.exceptions import ValidationError
from protean.fields import HasMany, HasOne, Identifier, Integer, String

domain = Domain()

@domain.aggregate
class Order:
    customer_id: Identifier(required=True)
    status: String(max_length=20, default="pending")
    line_items = HasMany("LineItem")
    shipping_info = HasOne("ShippingInfo")  # Optional: None until set

    @property
    def is_shippable(self) -> bool:
        """Check if order can be shipped."""
        return self.shipping_info is not None and len(self.line_items) > 0

    def place(self):
        if self.shipping_info is None:
            raise ValidationError(
                {"shipping_info": ["Shipping info is required to place the order"]}
            )
        self.status = "placed"

    def ship(self):
        if not self.is_shippable:
            raise ValidationError(
                {"_entity": ["Order needs shipping info and at least one item to ship"]}
            )
        self.status = "shipped"


@domain.entity(part_of="Order")
class LineItem:
    product_id: Identifier(required=True)
    quantity: Integer(required=True, min_value=1)
```

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
    # Protean adds `order` (a Reference to Order) and `order_id` automatically

    @property
    def full_address(self) -> str:
        """Get formatted full address."""
        parts = [self.address, self.city]
        if self.state:
            parts.append(self.state)
        parts.extend([self.postal_code, self.country])
        return ", ".join(parts)
```

### Setting HasOne Relationships

Creating instances needs an initialized domain and an active domain context:

```python
domain.init(traverse=False)

with domain.domain_context():
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

A `HasOne` field has no `add_*` helper. You set it by assignment.

### Accessing HasOne Relationships

```python
with domain.domain_context():
    # Access the related entity
    if order.shipping_info:
        print(f"Shipping to: {order.shipping_info.city}")
        print(f"Address: {order.shipping_info.full_address}")
        # Address: 123 Main Street, San Francisco, CA, 94102, USA
```

## Common Patterns

### Optional HasOne

A HasOne field is optional: it is `None` until you assign an entity. Check for `None` before using it, as `Order.is_shippable` does above:

```python
with domain.domain_context():
    draft = Order(customer_id="CUST-67890")
    assert draft.shipping_info is None
    assert draft.is_shippable is False
```

### Required HasOne (via validation)

You can't make a HasOne required at the field level. Enforce it in the aggregate method that needs it, as `Order.place()` does above:

```python
with domain.domain_context():
    try:
        draft.place()
    except ValidationError as exc:
        print(exc.messages["shipping_info"])  # ['Shipping info is required to place the order']
```

## Testing

```python
def test_hasone_relationship():
    with domain.domain_context():
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


test_hasone_relationship()
```

## Related

- [HasMany relationships](./with-hasmany.md): One-to-many entity relationships
- [Nested entities](./nested-entities.md): Entities containing other entities
- [Value objects](../../value-object/SKILL.md): When to use value objects instead
