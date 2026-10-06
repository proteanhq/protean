# Aggregates with Enclosed Entities

Aggregates can contain entities to form object graphs representing complex domain concepts. Entities within aggregates are accessible and modifiable only through the aggregate root.

## Overview

Use this pattern when:
- Your aggregate needs to manage a collection of related objects with identity
- You need one-to-one or one-to-many relationships
- Child objects don't make sense outside the parent aggregate's context
- You want to enforce transaction boundaries around the entire object graph

## Key Concepts

### HasOne Relationships

`HasOne` establishes a one-to-one relationship between the aggregate and an entity. The aggregate contains exactly one instance of the entity.

**When to use:**
- When each aggregate instance has exactly one associated entity
- Examples: Order has one ShippingInfo, User has one Profile

### HasMany Relationships

`HasMany` establishes a one-to-many relationship. The aggregate can contain multiple instances of the entity.

**When to use:**
- When each aggregate can have multiple related entities
- Examples: Order has many LineItems, Post has many Comments

## Code

The complete implementation is in [assets/aggregate_with_entity.py](../assets/aggregate_with_entity.py).

Key highlights:
- Entity declared with `@domain.entity(part_of="Order")` to associate it with the aggregate
- Automatic bidirectional references (child can access parent via `order_id` and `order`)
- Helper methods generated: `add_line_items()`, `remove_line_items()`
- Entities loaded eagerly with the aggregate

## Walkthrough

### Defining the Aggregate

```python
@domain.aggregate
class Order:
    customer_id: Identifier(required=True)
    status: String(max_length=20, default="draft")

    line_items = HasMany("LineItem")
    shipping_info = HasOne("ShippingInfo")
```

The aggregate declares associations using `HasMany` and `HasOne` fields. Note that you can use string references to entities that are defined later in the file.

### Defining Entities

```python
from decimal import Decimal as D


@domain.entity(part_of="Order")
class LineItem:
    product_id: String(required=True, max_length=50)
    quantity: Integer(required=True, min_value=1)
    unit_price: Decimal(precision=19, scale=4, required=True)

    order = Reference(Order)  # Bidirectional reference

    @property
    def subtotal(self) -> D:
        return self.quantity * self.unit_price


@domain.entity(part_of="Order")
class ShippingInfo:
    address: String(required=True, max_length=500)
    city: String(required=True, max_length=100)
```

Entities must specify which aggregate they belong to using the `part_of` parameter. This creates the relationship and ensures entities are managed correctly.

The `Reference` field creates a bidirectional relationship. While optional to declare explicitly, it documents the relationship and enables navigation from child to parent. Use `Reference` only for an entity pointing at its parent: the aggregate root, or the parent entity when the entity is nested. To point at another aggregate, hold its id in an `Identifier()` field.

Creating instances needs an initialized domain and an active domain context:

```python
domain.init(traverse=False)
```

### Working with Entities

**Adding entities:**

```python
with domain.domain_context():
    order = Order(customer_id="C123")
    item = LineItem(product_id="P1", quantity=2, unit_price="50.00")
    order.add_line_items(item)
```

Protean automatically generates `add_{field_name}()` methods for `HasMany` relationships. You can add single items or lists.

**Removing entities:**

```python
with domain.domain_context():
    order.remove_line_items(item)
```

Similarly, `remove_{field_name}()` methods are generated for `HasMany` relationships.

**Finding entities:**

```python
with domain.domain_context():
    first = LineItem(product_id="P1", quantity=2, unit_price="50.00")
    order.add_line_items(first)

    # One item by its fields. Raises ObjectNotFoundError when nothing matches
    found = order.get_one_from_line_items(id=first.id)
    assert found is first

    # All items whose fields equal the given values
    p1_items = order.filter_line_items(product_id="P1")
```

Both helpers take keyword arguments. `filter_{field_name}()` matches equality only; it has no `__gt`-style operators.

**Accessing entities:**

```python
with domain.domain_context():
    # Access all line items
    for item in order.line_items:
        print(item.product_id)

    # Access single entity (HasOne)
    if order.shipping_info:
        print(order.shipping_info.address)
```

**Bidirectional navigation:**

```python
with domain.domain_context():
    # From parent to child
    order.line_items[0].product_id

    # From child to parent
    order.line_items[0].order_id  # Just the ID
    order.line_items[0].order     # Full aggregate reference
```

## Entity Limits

Protean loads the entire aggregate object graph eagerly. To keep aggregates small, `check` flags one declaring more entity types than the configured `[lint] aggregate_size_limit` (default 5) as `AGGREGATE_TOO_LARGE`. It counts the entity classes in the cluster, so an aggregate with one `HasMany` of a thousand rows is never flagged for size. When flagged, consider:

- Splitting into multiple aggregates
- Making the entity an aggregate itself
- Redesigning aggregate boundaries

## Transaction Boundaries

All entities within an aggregate are persisted together in a single transaction:

```python
with domain.domain_context():
    order = Order(customer_id="C123")
    order.add_line_items(LineItem(product_id="P1", quantity=2, unit_price="50.00"))
    order.add_line_items(LineItem(product_id="P2", quantity=1, unit_price="75.00"))
    order.shipping_info = ShippingInfo(address="1 Main St", city="Springfield")

    # Single transaction persists order + all line items + shipping info
    domain.repository_for(Order).add(order)
```

Invariants run when the aggregate or one of its entities changes, not when `add()` persists it. A broken rule raises at the change, before the aggregate reaches the repository.

## Best Practices

1. **Entities belong to exactly one aggregate** - Use `part_of` to make this explicit
2. **Access entities only through the aggregate** - Don't reference entities directly from other aggregates
3. **Keep aggregate graphs small** - Avoid deeply nested structures (max 2 levels recommended)
4. **Use HasOne sparingly** - Often a value object is more appropriate
5. **Consider separate aggregates** - If entities have independent lifecycles, make them aggregates

## Common Patterns

### One-to-Many with Calculated Properties

Add a property to the `Order` aggregate that sums its entities:

```python
# fragment
@property
def total_amount(self) -> D:
    return sum((item.subtotal for item in self.line_items), D("0"))
```

### Adding Multiple Entities at Once

```python
with domain.domain_context():
    items = [
        LineItem(product_id="P1", quantity=2, unit_price="50.00"),
        LineItem(product_id="P2", quantity=1, unit_price="75.00"),
    ]
    order.add_line_items(items)
```

### Conditional Entity Access

```python
with domain.domain_context():
    if order.shipping_info:  # HasOne might be None
        print(order.shipping_info.address)
```

## Related

- [Aggregates with Value Objects](./with-value-objects.md)
- [Configuration Options](./configuration.md)
- [entity](../../entity/SKILL.md) - Detailed entity documentation
- [value-object](../../value-object/SKILL.md) - When to use value objects instead
