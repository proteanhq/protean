# Entity with HasMany Relationships

A `HasMany` field links an aggregate or entity to a collection of child entities in the same aggregate, such as `Order` and its `LineItem`s. It is the most common way to model a collection inside an aggregate. Use `HasOne` for a one-to-one link, a `List` of value objects when the items need no identity, and a separate aggregate when the children have a life of their own. Many-to-many relationships are not supported within an aggregate.

## Code

The complete implementation is in [assets/entity_with_hasmany.py](../assets/entity_with_hasmany.py).

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

A HasMany field is always a list, empty when there are no items, so these properties need no `None` checks. Start a money `sum()` at `D("0")` so an empty order totals `Decimal("0")`.

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

### Removing Entities from Collection

```python
with domain.domain_context():
    # Remove a specific entity
    item_to_remove = order.line_items[0]
    order.remove_line_items(item_to_remove)

    # Remove the matches of a filter
    order.remove_line_items(order.filter_line_items(product_id="PROD-002"))
```

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

## Testing

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

- [HasOne relationships](./with-hasone.md): One-to-one entity relationships
- [Nested entities](./nested-entities.md): Entities containing other entities
- [Aggregates](../../aggregate/SKILL.md): Aggregate patterns with entities
