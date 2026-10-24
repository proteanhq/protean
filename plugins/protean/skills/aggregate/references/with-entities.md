# Aggregates with Enclosed Entities

Aggregates can contain entities to form object graphs representing complex domain concepts. Entities within aggregates are accessible and modifiable only through the aggregate root.

## Code

The complete implementation is in [assets/aggregate_with_entity.py](../assets/aggregate_with_entity.py).

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

The aggregate declares associations using `HasMany` and `HasOne` fields. A string reference can name an entity defined later in the file.

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

Entities name the aggregate they belong to with the `part_of` parameter.

The `Reference` field creates a bidirectional relationship. Declaring it is optional: the child gets `order_id` and `order` either way. Use `Reference` only for an entity pointing at its parent: the aggregate root, or the parent entity when the entity is nested. To point at another aggregate, hold its id in an `Identifier()` field.

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

Protean generates `add_{field_name}()` methods for `HasMany` relationships. You can add single items or lists.

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

Protean loads the entire aggregate object graph eagerly. `check` flags an aggregate declaring more entity types than the configured `[lint] aggregate_size_limit` (default 5) as `AGGREGATE_TOO_LARGE`. It counts the entity classes in the cluster, so an aggregate with one `HasMany` of a thousand rows is never flagged for size. When an entity has a lifecycle of its own, make it an aggregate.

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

## Common Patterns

### Adding Multiple Entities at Once

```python
with domain.domain_context():
    items = [
        LineItem(product_id="P1", quantity=2, unit_price="50.00"),
        LineItem(product_id="P2", quantity=1, unit_price="75.00"),
    ]
    order.add_line_items(items)
```

## Related

- [Aggregates with Value Objects](./with-value-objects.md)
- [Configuration Options](./configuration.md)
- [entity](../../entity/SKILL.md): Detailed entity documentation
- [value-object](../../value-object/SKILL.md): When to use value objects instead
