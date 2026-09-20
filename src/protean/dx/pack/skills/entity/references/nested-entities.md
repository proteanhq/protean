# Nested Entities

Entities can contain other entities, creating a multi-level hierarchy within an aggregate. This pattern allows modeling complex domain structures while maintaining the aggregate boundary.

## Overview

Nested entities occur when an entity has HasMany or HasOne relationships to other entities, all belonging to the same aggregate. This creates a tree-like structure where the aggregate root is at the top, and entities can be nested multiple levels deep.

### When to Use Nested Entities

- You need multi-level hierarchical structures (e.g., Order → LineItem → LineItemNote)
- Child entities naturally belong to parent entities, not the aggregate root
- The nested structure represents cohesive domain concepts
- All entities in the hierarchy belong to the same transaction boundary

### When NOT to Use Nested Entities

- The hierarchy becomes too deep (more than 2-3 levels)
- Navigation becomes complex and error-prone
- The structure should be separate aggregates
- Performance concerns due to loading large object graphs

## Code

The complete implementation is in [assets/entity_nested.py](../assets/entity_nested.py).

Key highlights:
- Order aggregate contains LineItem entities
- LineItem entities contain LineItemNote and LineItemCustomization entities
- All entities belong to the same aggregate (Order)
- Navigation works across multiple levels
- Business logic can span the entire hierarchy

## Walkthrough

### The Aggregate Root

```python
@domain.aggregate
class Order:
    order_number: String(required=True, max_length=50)
    customer_id: String(required=True, max_length=50)
    status: String(max_length=20, default="draft")

    # First level: aggregate has many line items
    line_items = HasMany("LineItem")
```

The Order aggregate is the root of the hierarchy.

### First-Level Entities

```python
@domain.entity(part_of="Order")
class LineItem:
    product_id: String(required=True, max_length=50)
    product_name: String(required=True, max_length=200)
    quantity: Integer(required=True, min_value=1)
    unit_price: Float(required=True, min_value=0.0)

    # Second level: line item has many notes
    notes = HasMany("LineItemNote")

    # Second level: line item has many customizations
    customizations = HasMany("LineItemCustomization")

    # Reference back to aggregate
    order = Reference(Order)
```

LineItem is a first-level entity that contains other entities (notes and customizations).

### Second-Level Entities

```python
@domain.entity(part_of="Order")
class LineItemNote:
    content: Text(required=True)
    author: String(max_length=100, default="Customer")
    created_at: DateTime(default=datetime.now)

    # Reference back to parent LineItem (not Order!)
    line_item = Reference("LineItem")


@domain.entity(part_of="Order")
class LineItemCustomization:
    customization_type: String(required=True, max_length=50)
    details: Text(required=True)
    price: Float(default=0.0, min_value=0.0)

    # Reference back to parent LineItem
    line_item = Reference("LineItem")
```

Second-level entities:
- Still specify `part_of=Order` (the aggregate root)
- Reference their immediate parent entity (LineItem)
- Are persisted as part of the aggregate

### Building the Hierarchy

```python
# Create aggregate
order = Order(
    order_number="ORD-2024-001",
    customer_id="CUST-12345"
)

# Create first-level entity
item = LineItem(
    product_id="PROD-001",
    product_name="Custom T-Shirt",
    quantity=2,
    unit_price=29.99
)

# Create second-level entities (notes)
note1 = LineItemNote(content="Please use soft fabric", author="Customer")
note2 = LineItemNote(content="Gift wrap this item", author="Customer")
item.add_notes([note1, note2])

# Create second-level entities (customizations)
custom1 = LineItemCustomization(
    customization_type="Color",
    details="Navy Blue",
    price=0.0
)
custom2 = LineItemCustomization(
    customization_type="Engraving",
    details="Happy Birthday!",
    price=5.99
)
item.add_customizations([custom1, custom2])

# Add first-level entity to aggregate
order.add_line_items([item])
```

Build the hierarchy from bottom-up, then add to parent.

### Navigating the Hierarchy

```python
# Top-down navigation
for item in order.line_items:
    print(f"Item: {item.product_name}")

    # Navigate to second-level entities
    if item.notes:
        for note in item.notes:
            print(f"  Note: {note.content}")

    if item.customizations:
        for custom in item.customizations:
            print(f"  Customization: {custom.description}")

# Bottom-up navigation
if order.line_items and order.line_items[0].notes:
    first_note = order.line_items[0].notes[0]
    # Navigate from note to line item
    parent_item = first_note.line_item
    # Navigate from line item to order
    parent_order = parent_item.order
```

Navigation works both ways through reference fields.

### Business Logic Across Levels

```python
@domain.aggregate
class Order:
    line_items = HasMany("LineItem")

    @property
    def total_notes(self) -> int:
        """Count notes across all line items."""
        if not self.line_items:
            return 0
        return sum(
            len(item.notes) if item.notes else 0
            for item in self.line_items
        )

    def get_items_with_notes(self) -> list:
        """Get all line items that have notes."""
        if not self.line_items:
            return []
        return [
            item for item in self.line_items
            if item.notes and len(item.notes) > 0
        ]
```

The aggregate can compute values from nested entities at any level.

### Entity-Level Logic

```python
@domain.entity(part_of="Order")
class LineItem:
    notes = HasMany("LineItemNote")
    customizations = HasMany("LineItemCustomization")

    @property
    def customization_fee(self) -> float:
        """Calculate total customization fees."""
        if not self.customizations:
            return 0.0
        return sum(c.price for c in self.customizations)

    @property
    def has_special_instructions(self) -> bool:
        """Check if item has special notes."""
        return self.notes and len(self.notes) > 0

    def add_note(self, content: str, author: str = "Customer"):
        """Add a note to this line item."""
        note = LineItemNote(content=content, author=author)
        self.add_notes([note])
```

First-level entities encapsulate logic for their child entities.

## Common Patterns

### Helper Methods for Nested Creation

```python
@domain.entity(part_of="Order")
class LineItem:
    notes = HasMany("LineItemNote")
    customizations = HasMany("LineItemCustomization")

    def add_note(self, content: str, author: str = "Customer"):
        """Convenience method to add a note."""
        note = LineItemNote(content=content.strip(), author=author)
        self.add_notes([note])

    def add_customization(self, customization_type: str,
                         details: str, price: float = 0.0):
        """Convenience method to add a customization."""
        custom = LineItemCustomization(
            customization_type=customization_type,
            details=details,
            price=price
        )
        self.add_customizations([custom])
```

Provide helper methods to simplify nested entity creation.

### Computed Properties from Nested Entities

```python
@domain.entity(part_of="Order")
class LineItem:
    customizations = HasMany("LineItemCustomization")

    @property
    def total(self) -> float:
        """Total including customization fees."""
        base = self.quantity * self.unit_price
        custom_fees = sum(
            c.price for c in self.customizations
        ) if self.customizations else 0.0
        return base + custom_fees
```

Calculate values that depend on nested collections.

### Validation Across Levels

```python
@domain.aggregate
class Order:
    def validate_for_processing(self):
        """Validate entire order hierarchy."""
        if not self.line_items:
            raise ValueError("Order must have line items")

        for item in self.line_items:
            if item.quantity <= 0:
                raise ValueError(f"Invalid quantity for {item.product_name}")

            # Validate nested entities
            if item.customizations:
                for custom in item.customizations:
                    if custom.price < 0:
                        raise ValueError("Customization price cannot be negative")
```

Validation can traverse the entire hierarchy.

### Filtering Nested Collections

```python
@domain.aggregate
class Order:
    def get_items_with_customizations(self) -> list:
        """Get items that have customizations."""
        if not self.line_items:
            return []
        return [
            item for item in self.line_items
            if item.customizations and len(item.customizations) > 0
        ]

    def get_all_notes(self) -> list:
        """Get all notes from all line items."""
        all_notes = []
        if self.line_items:
            for item in self.line_items:
                if item.notes:
                    all_notes.extend(item.notes)
        return all_notes
```

Aggregate methods can collect and filter across nested levels.

## Guidelines for Nested Entities

### Depth Limits

**Recommended maximum depth: 2-3 levels**

```
✅ Good: Order → LineItem → LineItemNote (3 levels)
❌ Avoid: Order → LineItem → Note → Reply → SubReply (5 levels)
```

Deep nesting makes code hard to navigate and reason about.

### Reference Direction

**Always reference the immediate parent:**

```python
# ✅ Correct
@domain.entity(part_of="Order")
class LineItemNote:
    line_item = Reference("LineItem")  # Reference parent entity

# ❌ Wrong
@domain.entity(part_of="Order")
class LineItemNote:
    order = Reference(Order)  # Skip intermediate entity
```

### Performance Considerations

Be mindful of loading large nested structures:

```python
# If you have many line items with many notes each:
order = repository.get(order_id)
# This loads: Order + all LineItems + all Notes + all Customizations

# Consider limiting depth or using pagination for very large structures
```

## Testing

See [assets/entity_nested.py](../assets/entity_nested.py) for runnable examples.

To test nested entities:

```python
def test_nested_entities():
    order = Order(order_number="ORD-001", customer_id="C123")

    # Create nested structure
    item = LineItem(product_id="P1", product_name="T-Shirt",
                   quantity=2, unit_price=29.99)

    note = LineItemNote(content="Gift wrap please", author="Customer")
    item.add_notes([note])

    custom = LineItemCustomization(
        customization_type="Color",
        details="Blue",
        price=0.0
    )
    item.add_customizations([custom])

    order.add_line_items([item])

    # Test structure
    assert len(order.line_items) == 1
    assert len(order.line_items[0].notes) == 1
    assert len(order.line_items[0].customizations) == 1

    # Test navigation
    assert note.line_item == item
    assert item.order == order
```

## Related

- [HasOne relationships](./with-hasone.md) - One-to-one entity relationships
- [HasMany relationships](./with-hasmany.md) - One-to-many entity relationships
- [Aggregates](../../aggregate/SKILL.md) - Aggregate design patterns
