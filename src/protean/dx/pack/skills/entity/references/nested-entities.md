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
from datetime import datetime
from decimal import Decimal as D  # stdlib Decimal, aliased so it does not clash with the field

from protean import Domain, invariant
from protean.exceptions import ValidationError
from protean.fields import DateTime, Decimal, HasMany, Identifier, Integer, String, Text

domain = Domain()

@domain.aggregate
class Order:
    order_number: String(required=True, max_length=50)
    customer_id: Identifier(required=True)
    status: String(max_length=20, default="draft")

    # First level: aggregate has many line items
    line_items = HasMany("LineItem")

    @property
    def total_notes(self) -> int:
        """Count notes across all line items."""
        return sum(len(item.notes) for item in self.line_items)

    def get_items_with_notes(self) -> list:
        """Get all line items that have notes."""
        return [item for item in self.line_items if item.notes]

    def get_all_notes(self) -> list:
        """Get all notes from all line items."""
        all_notes = []
        for item in self.line_items:
            all_notes.extend(item.notes)
        return all_notes

    @invariant.post
    def customization_fees_cannot_exceed_item_price(self):
        for item in self.line_items:
            if item.customization_fee > item.quantity * item.unit_price:
                raise ValidationError(
                    {"_entity": [f"Customization fees exceed the price of {item.product_name}"]}
                )
```

The Order aggregate is the root of the hierarchy. Its methods read the nested entities at every level.

### First-Level Entities

```python
@domain.entity(part_of="Order")
class LineItem:
    product_id: Identifier(required=True)
    product_name: String(required=True, max_length=200)
    quantity: Integer(required=True, min_value=1)
    unit_price: Decimal(precision=19, scale=4, required=True, min_value=0)

    # Second level: line item has many notes
    notes = HasMany("LineItemNote")

    # Second level: line item has many customizations
    customizations = HasMany("LineItemCustomization")

    # Protean adds `order` (a Reference to Order) and `order_id` automatically

    @property
    def customization_fee(self) -> D:
        """Calculate total customization fees."""
        return sum((c.price for c in self.customizations), D("0"))

    @property
    def total(self) -> D:
        """Total including customization fees."""
        return self.quantity * self.unit_price + self.customization_fee

    @property
    def has_special_instructions(self) -> bool:
        """Check if item has special notes."""
        return len(self.notes) > 0

    def add_note(self, content: str, author: str = "Customer"):
        """Convenience method to add a note."""
        note = LineItemNote(content=content.strip(), author=author)
        self.add_notes([note])

    def add_customization(self, customization_type: str,
                          details: str, price: D = D("0")):
        """Convenience method to add a customization."""
        custom = LineItemCustomization(
            customization_type=customization_type,
            details=details,
            price=price
        )
        self.add_customizations([custom])
```

LineItem is a first-level entity that contains other entities (notes and customizations).

### Second-Level Entities

```python
@domain.entity(part_of=LineItem)
class LineItemNote:
    content: Text(required=True)
    author: String(max_length=100, default="Customer")
    created_at: DateTime(default=datetime.now)
    # Protean adds `line_item` (a Reference to LineItem) and `line_item_id`


@domain.entity(part_of=LineItem)
class LineItemCustomization:
    customization_type: String(required=True, max_length=50)
    details: Text(required=True)
    price: Decimal(precision=19, scale=4, default=0, min_value=0)
    # Protean adds `line_item` (a Reference to LineItem) and `line_item_id`
```

Second-level entities:
- Are `part_of` their immediate parent entity (`LineItem`), not the aggregate root
- Pass the parent as a class (`part_of=LineItem`). A string `part_of` resolves only to an aggregate, so define the parent entity first.
- Get a `Reference` back to the parent entity automatically. Do not declare it yourself.
- Still belong to the `Order` aggregate and are persisted with it

### Building the Hierarchy

Creating instances needs an initialized domain and an active domain context:

```python
domain.init(traverse=False)

with domain.domain_context():
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
        unit_price=D("29.99")
    )

    # Create second-level entities (notes)
    note1 = LineItemNote(content="Please use soft fabric", author="Customer")
    note2 = LineItemNote(content="Gift wrap this item", author="Customer")
    item.add_notes([note1, note2])

    # Create second-level entities (customizations)
    custom1 = LineItemCustomization(
        customization_type="Color",
        details="Navy Blue",
    )
    custom2 = LineItemCustomization(
        customization_type="Engraving",
        details="Happy Birthday!",
        price=D("5.99")
    )
    item.add_customizations([custom1, custom2])

    # Add first-level entity to aggregate
    order.add_line_items([item])
```

Build the hierarchy from bottom-up, then add to parent.

### Navigating the Hierarchy

```python
with domain.domain_context():
    # Top-down navigation
    for item in order.line_items:
        print(f"Item: {item.product_name}")

        # Navigate to second-level entities
        for note in item.notes:
            print(f"  Note: {note.content}")

        for custom in item.customizations:
            print(f"  Customization: {custom.customization_type}: {custom.details}")

    # Bottom-up navigation
    first_note = order.line_items[0].notes[0]
    # Navigate from note to line item
    parent_item = first_note.line_item
    # Navigate from line item to order
    parent_order = parent_item.order
```

Navigation works both ways through reference fields. A `HasMany` field is always a list, empty when there are no items, so you can loop over it without a `None` check.

## Common Patterns

The patterns below are excerpts from the `Order` and `LineItem` classes defined above.

### Business Logic Across Levels

```python
# fragment
# In Order
@property
def total_notes(self) -> int:
    """Count notes across all line items."""
    return sum(len(item.notes) for item in self.line_items)
```

The aggregate can compute values from nested entities at any level.

### Helper Methods for Nested Creation

```python
# fragment
# In LineItem
def add_note(self, content: str, author: str = "Customer"):
    """Convenience method to add a note."""
    note = LineItemNote(content=content.strip(), author=author)
    self.add_notes([note])
```

Helper methods on the parent entity keep nested creation in one place:

```python
with domain.domain_context():
    item.add_note("Deliver after 5pm")
    item.add_customization("Size", "Large")
```

### Computed Properties from Nested Entities

```python
# fragment
# In LineItem
@property
def customization_fee(self) -> D:
    """Calculate total customization fees."""
    return sum((c.price for c in self.customizations), D("0"))
```

Start `sum()` at `D("0")` so the result stays a `Decimal` when there are no customizations.

### Validation Across Levels

Rules that span the hierarchy belong in an invariant on the aggregate root. A change to any entity in the hierarchy runs the root's post-invariants, so the rule holds at every level:

```python
with domain.domain_context():
    mug = LineItem(product_id="PROD-002", product_name="Mug", quantity=1, unit_price=D("15.99"))
    gift_order = Order(order_number="ORD-2024-002", customer_id="CUST-12345", line_items=[mug])

    try:
        # $50 of engraving on a $15.99 line item
        mug.add_customization("Engraving", "A very long message", D("50"))
    except ValidationError as exc:
        print(exc.messages["_entity"])  # ['Customization fees exceed the price of Mug']
```

Field constraints such as `min_value=1` on `quantity` and `min_value=0` on `price` already cover single values, so the invariant checks only the rule that spans levels.

## Guidelines for Nested Entities

### Depth Limits

**Recommended maximum depth: 2-3 levels**

```
✅ Good: Order → LineItem → LineItemNote (3 levels)
❌ Avoid: Order → LineItem → Note → Reply → SubReply (5 levels)
```

Deep nesting makes code hard to navigate and reason about.

### Parent Direction

**Make a nested entity `part_of` its immediate parent:**

```python
# fragment
# ✅ Correct: part_of the parent entity; line_item is added automatically
@domain.entity(part_of=LineItem)
class LineItemNote:
    content: Text(required=True)

# ❌ Wrong: part_of the root, with a hand-written Reference to the parent entity
@domain.entity(part_of="Order")
class LineItemNote:
    content: Text(required=True)
    line_item = Reference("LineItem")
```

A `Reference` field is only for an entity pointing back to its own parent. Protean adds it for you from `part_of`.

### Performance Considerations

Be mindful of loading large nested structures:

```python
with domain.domain_context():
    repository = domain.repository_for(Order)
    repository.add(order)

    # If you have many line items with many notes each:
    order = repository.get(order.id)
    # This loads: Order + all LineItems + all Notes + all Customizations
```

Consider limiting depth for very large structures.

## Testing

See [assets/entity_nested.py](../assets/entity_nested.py) for runnable examples.

To test nested entities:

```python
def test_nested_entities():
    with domain.domain_context():
        order = Order(order_number="ORD-001", customer_id="C123")

        # Create nested structure
        item = LineItem(product_id="P1", product_name="T-Shirt",
                        quantity=2, unit_price=D("29.99"))

        note = LineItemNote(content="Gift wrap please", author="Customer")
        item.add_notes([note])

        custom = LineItemCustomization(
            customization_type="Color",
            details="Blue",
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


test_nested_entities()
```

## Related

- [HasOne relationships](./with-hasone.md) - One-to-one entity relationships
- [HasMany relationships](./with-hasmany.md) - One-to-many entity relationships
- [Aggregates](../../aggregate/SKILL.md) - Aggregate design patterns
