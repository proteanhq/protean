# Entity with HasMany Relationships

Entities can have one-to-many relationships with other entities using the `HasMany` field. This is the most common pattern for modeling collections of related entities within an aggregate.

## Overview

A `HasMany` relationship creates a one-to-many association between a parent entity and multiple child entities. The parent "has many" instances of the child entity.

### When to Use HasMany

- An entity needs to contain multiple instances of another entity (e.g., Order → LineItems)
- The relationship is one-to-many
- Each child entity has its own identity
- Both entities belong to the same aggregate
- You need to add, remove, and iterate over child entities

### When NOT to Use HasMany

- The relationship is one-to-one (use `HasOne` instead)
- The related data doesn't need identity (use a `List` of value objects)
- You need many-to-many relationships (not supported within aggregates)
- The child entities should be a separate aggregate

## Code

The complete implementation is in [assets/entity_with_hasmany.py](../assets/entity_with_hasmany.py).

Key highlights:
- `LineItem` entities are associated with `Order` aggregate via one-to-many relationship
- Order defines `line_items = HasMany("LineItem")`
- LineItem gets automatic reference back to Order
- Collection methods: `add_line_items()`, `remove_line_items()`
- Business logic can iterate over and compute from child entities

## Walkthrough

### The Aggregate

```python
from decimal import Decimal as D  # stdlib Decimal, aliased so it does not clash with the field

from protean import Domain
from protean.exceptions import ObjectNotFoundError, ValidationError
from protean.fields import Decimal, Float, HasMany, Identifier, Integer, String

domain = Domain()

@domain.aggregate
class Order:
    order_number: String(required=True, max_length=50)
    customer_id: Identifier(required=True)
    status: String(max_length=20, default="draft")

    # One-to-many: order has many line items
    line_items = HasMany("LineItem")
```

The Order aggregate defines a HasMany relationship to LineItem entities. This creates a collection that can contain zero or more line items.

### The Child Entity

```python
@domain.entity(part_of="Order")
class LineItem:
    product_id: Identifier(required=True)
    product_name: String(required=True, max_length=200)
    quantity: Integer(required=True, min_value=1)
    unit_price: Decimal(precision=19, scale=4, required=True, min_value=0)
    discount_percent: Float(min_value=0.0, max_value=100.0, default=0.0)
    # Protean adds `order` (a Reference to Order) and `order_id` automatically

    @property
    def subtotal(self) -> D:
        return self.quantity * self.unit_price
```

The LineItem entity:
- Must specify `part_of="Order"`
- Gets automatic `order` reference field
- Gets automatic `order_id` shadow field
- Can have its own business logic

### Computed Properties from Collection

```python
@domain.aggregate
class Order:
    order_number: String(required=True, max_length=50)
    customer_id: Identifier(required=True)
    status: String(max_length=20, default="draft")
    line_items = HasMany("LineItem")

    @property
    def total_amount(self) -> D:
        """Calculate total from all line items."""
        return sum((item.subtotal for item in self.line_items), D("0"))

    @property
    def total_quantity(self) -> int:
        """Calculate total quantity across all items."""
        return sum(item.quantity for item in self.line_items)

    @property
    def item_count(self) -> int:
        """Get number of line items."""
        return len(self.line_items)
```

Aggregates often compute values by iterating over their HasMany collections. A HasMany field is always a list, empty when there are no items, so these properties need no `None` checks. Start a money `sum()` at `D("0")` so an empty order totals `Decimal("0")`.

### Business Logic with Collections

```python
@domain.aggregate
class Order:
    order_number: String(required=True, max_length=50)
    customer_id: Identifier(required=True)
    status: String(max_length=20, default="draft")
    line_items = HasMany("LineItem")

    @property
    def total_amount(self) -> D:
        return sum((item.subtotal for item in self.line_items), D("0"))

    def add_item(self, product_id: str, product_name: str,
                 quantity: int, unit_price: D):
        """Add a new line item. The LineItem fields validate the values."""
        item = LineItem(
            product_id=product_id,
            product_name=product_name,
            quantity=quantity,
            unit_price=unit_price
        )
        self.add_line_items([item])

    def remove_item(self, product_id: str):
        """Remove the items for a product."""
        items = self.filter_line_items(product_id=product_id)
        if not items:
            raise ValidationError(
                {"line_items": [f"Product {product_id} is not in the order"]}
            )
        self.remove_line_items(items)

    def clear_items(self):
        """Remove all line items."""
        self.remove_line_items(list(self.line_items))

    def place(self):
        """Place the order."""
        if not self.line_items:
            raise ValidationError({"line_items": ["Cannot place an empty order"]})
        self.status = "placed"
```

Encapsulate collection operations in aggregate methods for better encapsulation.

### Adding Entities to Collection

Creating instances needs an initialized domain and an active domain context:

```python
domain.init(traverse=False)

with domain.domain_context():
    # Create the aggregate
    order = Order(
        order_number="ORD-2024-001",
        customer_id="CUST-12345"
    )

    # Create child entities
    item1 = LineItem(
        product_id="PROD-001",
        product_name="Laptop",
        quantity=1,
        unit_price=D("999.99")
    )
    item2 = LineItem(
        product_id="PROD-002",
        product_name="Mouse",
        quantity=2,
        unit_price=D("29.99")
    )

    # Add entities to the collection
    order.add_line_items([item1, item2])
```

Protean automatically generates `add_<collection_name>()` methods for HasMany fields.

### Accessing Collection

```python
with domain.domain_context():
    # Get count
    item_count = len(order.line_items)

    # Check if empty
    if not order.line_items:
        print("No items in order")

    # Iterate over entities
    for item in order.line_items:
        print(f"{item.product_name}: ${item.subtotal:.2f}")

    # Access by index
    first_item = order.line_items[0]

    # Get one item by its id; raises ObjectNotFoundError when nothing matches
    laptop = order.get_one_from_line_items(id=item1.id)
    assert laptop is item1

    # Filter items by field values (equality only)
    mice = order.filter_line_items(product_id="PROD-002")
```

The HasMany collection behaves like a Python list. `get_one_from_line_items()` and `filter_line_items()` take keyword arguments and match on equality only. For other comparisons, such as a price above 100, use a list comprehension.

### Updating Entities in Collection

```python
with domain.domain_context():
    # Find and update
    for item in order.line_items:
        if item.product_id == "PROD-001":
            item.quantity = 5  # Update directly

    # Or fetch by id and update
    laptop = order.get_one_from_line_items(id=item1.id)
    assert laptop is item1
    laptop.quantity = 5
```

Entities in the collection are mutable and can be updated directly.

### Removing Entities from Collection

```python
with domain.domain_context():
    # Remove a specific entity
    item_to_remove = order.line_items[0]
    order.remove_line_items(item_to_remove)

    # Remove the matches of a filter
    order.remove_line_items(order.filter_line_items(product_id="PROD-002"))
```

Protean automatically generates `remove_<collection_name>()` methods.

## Common Patterns

### Collection Initialization

```python
with domain.domain_context():
    # Empty collection (default)
    order = Order(order_number="ORD-2024-002", customer_id="C123")
    assert order.line_items == []

    # Add items
    order.add_item("PROD-001", "Laptop", 1, D("999.99"))
    order.add_item("PROD-003", "Monitor", 2, D("249.50"))
```

A HasMany field starts as an empty list and grows as entities are added.

### Iterating Collections

```python
with domain.domain_context():
    for item in order.line_items:
        print(item.product_name)

    total = sum((item.subtotal for item in order.line_items), D("0"))
```

Iterate directly. An empty collection is an empty list, so no `None` check is needed.

### Filtering Collections

```python
with domain.domain_context():
    # Find all items with discount
    discounted_items = [
        item for item in order.line_items
        if item.discount_percent > 0
    ]

    # Find high-value items
    expensive_items = [
        item for item in order.line_items
        if item.unit_price > 100
    ]
```

Use list comprehensions for comparisons other than equality.

### Sorting Collections

```python
with domain.domain_context():
    # Sort by price
    sorted_items = sorted(
        order.line_items,
        key=lambda item: item.unit_price,
        reverse=True
    )
```

Collections can be sorted using Python's built-in functions.

## Testing

See [assets/entity_with_hasmany.py](../assets/entity_with_hasmany.py) for runnable examples.

To test HasMany relationships:

```python
def test_hasmany_relationship():
    with domain.domain_context():
        order = Order(customer_id="C123", order_number="ORD-001")

        # Add items
        item1 = LineItem(product_id="P1", product_name="Item 1",
                         quantity=2, unit_price=D("50.00"))
        item2 = LineItem(product_id="P2", product_name="Item 2",
                         quantity=1, unit_price=D("30.00"))
        order.add_line_items([item1, item2])

        # Test collection
        assert len(order.line_items) == 2
        assert order.line_items[0].product_id == "P1"
        assert order.total_amount == D("130.00")

        # Test bidirectional reference
        assert item1.order == order
        assert item1.order_id == order.id

        # Test removal
        order.remove_line_items(item2)
        assert len(order.line_items) == 1

        # Test a lookup miss
        try:
            order.get_one_from_line_items(id="missing")
            raise AssertionError("expected ObjectNotFoundError")
        except ObjectNotFoundError:
            pass


test_hasmany_relationship()
```

## Related

- [HasOne relationships](./with-hasone.md) - One-to-one entity relationships
- [Nested entities](./nested-entities.md) - Entities containing other entities
- [Aggregates](../../aggregate/SKILL.md) - Aggregate patterns with entities
