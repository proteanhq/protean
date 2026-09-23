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
@domain.aggregate
class Order:
    order_number: String(required=True, max_length=50)
    customer_id: String(required=True, max_length=50)
    status: String(max_length=20, default="draft")

    # One-to-many: order has many line items
    line_items = HasMany("LineItem")
```

The Order aggregate defines a HasMany relationship to LineItem entities. This creates a collection that can contain zero or more line items.

### The Child Entity

```python
@domain.entity(part_of="Order")
class LineItem:
    product_id: String(required=True, max_length=50)
    product_name: String(required=True, max_length=200)
    quantity: Integer(required=True, min_value=1)
    unit_price: Float(required=True, min_value=0.0)
    discount_percent: Float(min_value=0.0, max_value=100.0, default=0.0)

    # Automatic reference back to parent
    order = Reference(Order)
```

The LineItem entity:
- Must specify `part_of=Order`
- Gets automatic `order` reference field
- Gets automatic `order_id` shadow field
- Can have its own business logic

### Adding Entities to Collection

```python
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
    unit_price=999.99
)
item2 = LineItem(
    product_id="PROD-002",
    product_name="Mouse",
    quantity=2,
    unit_price=29.99
)

# Add entities to the collection
order.add_line_items([item1, item2])
```

Protean automatically generates `add_<collection_name>()` methods for HasMany fields.

### Accessing Collection

```python
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

# Find specific items
laptop = next(
    (item for item in order.line_items if item.product_id == "PROD-001"),
    None
)
```

The HasMany collection behaves like a Python list.

### Removing Entities from Collection

```python
# Remove a specific entity
item_to_remove = order.line_items[0]
order.remove_line_items(item_to_remove)

# Remove by finding first
item = next(
    (i for i in order.line_items if i.product_id == "PROD-002"),
    None
)
if item:
    order.remove_line_items(item)
```

Protean automatically generates `remove_<collection_name>()` methods.

### Updating Entities in Collection

```python
# Find and update
for item in order.line_items:
    if item.product_id == "PROD-001":
        item.quantity = 5  # Update directly

# Or find first and update
laptop = next(
    (i for i in order.line_items if i.product_id == "PROD-001"),
    None
)
if laptop:
    laptop.quantity = 5
```

Entities in the collection are mutable and can be updated directly.

### Computed Properties from Collection

```python
@domain.aggregate
class Order:
    line_items = HasMany("LineItem")

    @property
    def total_amount(self) -> float:
        """Calculate total from all line items."""
        if not self.line_items:
            return 0.0
        return sum(item.subtotal for item in self.line_items)

    @property
    def total_quantity(self) -> int:
        """Calculate total quantity across all items."""
        if not self.line_items:
            return 0
        return sum(item.quantity for item in self.line_items)

    @property
    def item_count(self) -> int:
        """Get number of line items."""
        return len(self.line_items) if self.line_items else 0
```

Aggregates often compute values by iterating over their HasMany collections.

### Business Logic with Collections

```python
@domain.aggregate
class Order:
    line_items = HasMany("LineItem")

    def add_item(self, product_id: str, product_name: str,
                 quantity: int, unit_price: float):
        """Add a new line item with validation."""
        if quantity <= 0:
            raise ValueError("Quantity must be positive")
        if unit_price < 0:
            raise ValueError("Unit price cannot be negative")

        item = LineItem(
            product_id=product_id,
            product_name=product_name,
            quantity=quantity,
            unit_price=unit_price
        )
        self.add_line_items([item])

    def remove_item(self, product_id: str):
        """Remove item by product ID."""
        item = next(
            (i for i in self.line_items if i.product_id == product_id),
            None
        )
        if item is None:
            raise ValueError(f"Product {product_id} not found")
        self.remove_line_items(item)

    def clear_items(self):
        """Remove all line items."""
        if self.line_items:
            items_to_remove = list(self.line_items)
            for item in items_to_remove:
                self.remove_line_items(item)

    def place(self):
        """Place the order."""
        if not self.line_items:
            raise ValueError("Cannot place empty order")
        self.status = "placed"
```

Encapsulate collection operations in aggregate methods for better encapsulation.

## Common Patterns

### Collection Initialization

```python
# Empty collection (default)
order = Order(customer_id="C123")
# order.line_items is None initially

# Add items
order.add_line_items([item1, item2])
```

HasMany collections are None by default and become a list when entities are added.

### Safe Collection Iteration

```python
# Always check before iterating
if order.line_items:
    for item in order.line_items:
        process(item)

# Or use conditional expression
total = sum(item.total for item in order.line_items) if order.line_items else 0.0
```

Check for None before accessing collection to avoid errors.

### Filtering Collections

```python
# Find all items with discount
discounted_items = [
    item for item in order.line_items
    if item.discount_percent > 0
] if order.line_items else []

# Find high-value items
expensive_items = [
    item for item in order.line_items
    if item.unit_price > 100
] if order.line_items else []
```

Use list comprehensions to filter collections.

### Sorting Collections

```python
# Sort by price
if order.line_items:
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
    order = Order(customer_id="C123", order_number="ORD-001")

    # Add items
    item1 = LineItem(product_id="P1", product_name="Item 1",
                     quantity=2, unit_price=50.0)
    item2 = LineItem(product_id="P2", product_name="Item 2",
                     quantity=1, unit_price=30.0)
    order.add_line_items([item1, item2])

    # Test collection
    assert len(order.line_items) == 2
    assert order.line_items[0].product_id == "P1"

    # Test bidirectional reference
    assert item1.order == order
    assert item1.order_id == order.id

    # Test removal
    order.remove_line_items(item2)
    assert len(order.line_items) == 1
```

## Related

- [HasOne relationships](./with-hasone.md) - One-to-one entity relationships
- [Nested entities](./nested-entities.md) - Entities containing other entities
- [Aggregates](../../aggregate/SKILL.md) - Aggregate patterns with entities
