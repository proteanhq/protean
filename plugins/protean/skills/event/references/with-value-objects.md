# Events with Value Objects

An event can carry value objects for structured, immutable data such as `Money` or `Address`. The same value object classes serve the aggregate and its events.

The complete implementation is in [assets/event_with_value_object.py](../assets/event_with_value_object.py).

## Common Value Objects in Events

The events on this page belong to these aggregates. `Order` is defined in [Creating Events with Value Objects](#creating-events-with-value-objects).

```python
@domain.aggregate
class User:
    email: String()
```

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

## Multiple Value Objects in One Event

Events can contain multiple value objects:

```python
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

@domain.event(part_of="Order")
class OrderPlaced:
    __version__ = 1

    order_id: String(required=True, identifier=True)
    customer_id: String(required=True)
    total = ValueObject(Money, required=True)
    shipping_address = ValueObject(Address, required=True)
    placed_at: DateTime(required=True)

@domain.aggregate
class Order:
    order_id: String(required=True, identifier=True)
    customer_id: String(required=True)
    status: String(default="draft")
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
domain.init(traverse=False)

with domain.domain_context():
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

## Related

- [Delta Events](./delta-events.md): Incremental state changes
- [Fact Events](./fact-events.md): Complete state snapshots
- `value-object`: Detailed value object patterns
