# Event Versioning

Event versioning lets an event's schema change while existing consumers keep working. Events stay in the event store for good, so a consumer can meet an old version and a new one side by side.

The complete implementation is in [assets/event_versioning.py](../assets/event_versioning.py).

## Basic Versioning

The examples on this page use these aggregates and value objects:

```python
@domain.value_object
class Money:
    amount: Decimal(precision=19, scale=4, required=True)
    currency: String(max_length=3, default="USD")


@domain.value_object
class Address:
    street: String(required=True)
    city: String(required=True)


@domain.aggregate
class Order:
    customer_id: String()


@domain.aggregate
class Product:
    name: String()


@domain.aggregate
class User:
    email: String()
```

`__version__` defaults to `1`. Declare it from the start, so the version is visible in the class when the schema changes:

```python
@domain.event(part_of="Order")
class OrderPlaced:
    __version__ = 1  # Always version from the beginning

    order_id: String(required=True, identifier=True)
    customer_id: String(required=True)
    placed_at: DateTime(required=True)
```

## Version Evolution Strategies

### 1. Backward Compatible Changes (Same Version)

Some changes don't require a new version:

**Adding optional fields:**
```python
@domain.event(part_of="Order")
class OrderPlaced:
    __version__ = 1

    order_id: String(required=True, identifier=True)
    customer_id: String(required=True)
    placed_at: DateTime(required=True)
    # New optional field - backward compatible
    notes: String()  # Old events won't have this, default is None
```

**Adding default values:**
```python
@domain.event(part_of="Product")
class ProductCreated:
    __version__ = 1

    product_id: String(required=True, identifier=True)
    name: String(required=True)
    # New field with default - backward compatible
    category: String(default="uncategorized")
```

### 2. Breaking Changes (New Version)

Breaking changes require incrementing the version:

**Adding required fields:**
```python
# v1 - original
@domain.event(part_of="Order")
class OrderPlaced:
    __version__ = 1

    order_id: String(required=True, identifier=True)
    customer_id: String(required=True)

# v2 - added required field
@domain.event(part_of="Order")
class OrderPlaced:
    __version__ = 2

    order_id: String(required=True, identifier=True)
    customer_id: String(required=True)
    total = ValueObject(Money, required=True)  # New required field
```

**Removing fields:**
```python
# v1 - original
@domain.event(part_of="User")
class UserRegistered:
    __version__ = 1

    user_id: String(required=True, identifier=True)
    username: String(required=True)
    email: String(required=True)

# v2 - removed username field
@domain.event(part_of="User")
class UserRegistered:
    __version__ = 2

    user_id: String(required=True, identifier=True)
    email: String(required=True)
    # username field removed
```

**Changing field types:**
```python
# v1 - original
@domain.event(part_of="Product")
class PriceChanged:
    __version__ = 1

    product_id: String(required=True, identifier=True)
    new_price: Decimal(precision=19, scale=4, required=True)  # Simple float

# v2 - changed to value object
@domain.event(part_of="Product")
class PriceChanged:
    __version__ = 2

    product_id: String(required=True, identifier=True)
    new_price = ValueObject(Money, required=True)  # Now a value object
```

## Version Migration Patterns

### Pattern 1: A New Event for a New Fact

When the change records a different business fact, add a new event type with its own name, starting at version 1:

```python
# The existing event keeps its name and its version
@domain.event(part_of="Order")
class OrderPlaced:
    __version__ = 1

    order_id: String(required=True, identifier=True)
    customer_id: String(required=True)

# A different fact gets its own event
@domain.event(part_of="Order")
class OrderPriced:
    __version__ = 1

    order_id: String(required=True, identifier=True)
    total = ValueObject(Money, required=True)
    items: List()
```

Do not put a version number in a class name, such as `OrderPlacedV2`. The framework links the versions of an event by its type name, so no upcaster can turn a stored `OrderPlaced` into an `OrderPlacedV2`. When the fact stays the same and only its shape changes, keep the name, raise `__version__` and add an upcaster (Pattern 2).

### Pattern 2: Upcasting

Transform old event versions to new format when reading:

```python
from protean.core.upcaster import BaseUpcaster


@domain.event(part_of="Order")
class OrderPlaced:
    __version__ = 2

    order_id: String(required=True, identifier=True)
    customer_id: String(required=True)
    total = ValueObject(Money, required=True)


@domain.upcaster(event_type=OrderPlaced, from_version=1, to_version=2)
class UpcastOrderPlacedV1ToV2(BaseUpcaster):
    def upcast(self, data: dict) -> dict:
        data["total"] = {"amount": 0.0, "currency": "USD"}  # v1 had no total
        return data
```

`event_type` is the current event class. The framework applies the upcaster when it reads a stored v1 event. See the `upcaster` skill for chains, rules and testing.

### Pattern 3: Weak Schema

Use flexible fields for evolving data:

```python
@domain.event(part_of="Order")
class OrderPlaced:
    __version__ = 1

    order_id: String(required=True, identifier=True)
    customer_id: String(required=True)

    # Flexible metadata field for evolution
    metadata: Dict()  # Can add new data without schema changes
```

## Versioning Best Practices

### 1. Document Version Changes

```python
@domain.event(part_of="Order")
class OrderPlaced:
    """Order placement event.

    Version History:
    - v1: Initial version with basic order info
    - v2: Added total and items fields (2024-02-09)
    - v3: Changed price to Money value object (2024-03-15)
    """
    __version__ = 3

    order_id: String(required=True, identifier=True)
    customer_id: String(required=True)
    total = ValueObject(Money, required=True)
    items: List()
```

### 2. Test Multiple Versions

The version is not a payload field. It comes from the class attribute, and the event carries it in its metadata. Passing `__version__` as a keyword raises `ValidationError: {'__version__': ['Extra inputs are not permitted']}`.

Test that the current version builds and that the upcaster turns an old payload into a valid current one:

```python
from decimal import Decimal as D


@domain.event(part_of="Order")
class OrderPlaced:
    __version__ = 2

    order_id: String(required=True, identifier=True)
    customer_id: String(required=True)
    total = ValueObject(Money, required=True)


@domain.upcaster(event_type=OrderPlaced, from_version=1, to_version=2)
class UpcastOrderPlacedV1ToV2(BaseUpcaster):
    def upcast(self, data: dict) -> dict:
        data["total"] = {"amount": 0.0, "currency": "USD"}
        return data


def test_v2_event_carries_its_version():
    event = OrderPlaced(
        order_id="ORD-001",
        customer_id="CUST-123",
        total=Money(amount=99.99, currency="USD"),
    )
    assert event.total.amount == D("99.99")
    assert event._metadata.domain.version == 2
    assert event._metadata.headers.type.endswith(".v2")


def test_v1_payload_upcasts_to_v2():
    v1_data = {"order_id": "ORD-001", "customer_id": "CUST-123"}
    data = UpcastOrderPlacedV1ToV2().upcast(v1_data)
    event = OrderPlaced(**data)
    assert event.total.amount == D("0.00")


domain.init(traverse=False)
with domain.domain_context():
    test_v2_event_carries_its_version()
    test_v1_payload_upcasts_to_v2()
```

## Common Versioning Scenarios

### Scenario 1: Splitting into Multiple Events

```python
# v1 - monolithic event
@domain.event(part_of="Order")
class OrderUpdated:
    __version__ = 1
    order_id: String(required=True, identifier=True)
    update_type: String(required=True)  # "status", "address", "payment"
    new_value: String()

# v2 - split into focused events
@domain.event(part_of="Order")
class OrderStatusChanged:
    __version__ = 1
    order_id: String(required=True, identifier=True)
    new_status: String(required=True)

@domain.event(part_of="Order")
class OrderAddressChanged:
    __version__ = 1
    order_id: String(required=True, identifier=True)
    new_address = ValueObject(Address, required=True)
```

## Related

- [Delta Events](./delta-events.md): Incremental state changes
- [Fact Events](./fact-events.md): Complete state snapshots
- [Anti-patterns](./anti-patterns.md): Common versioning mistakes
