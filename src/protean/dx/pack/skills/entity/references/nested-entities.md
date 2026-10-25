# Nested Entities

An entity can hold other entities through `HasMany` or `HasOne`, so an aggregate can be a tree several levels deep, such as Order, then LineItem, then LineItemNote. Every entity in the tree belongs to the same aggregate and is saved in the same transaction. When a branch has a life of its own, make it a separate aggregate.

## Code

The complete implementation is in [assets/entity_nested.py](../assets/entity_nested.py).

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

Start `sum()` at `D("0")` so `customization_fee` stays a `Decimal` when there are no customizations.

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
- Name the parent as a class (`part_of=LineItem`) or a string (`part_of="LineItem"`)
- Get a `Reference` back to the parent entity automatically, as [Parent Direction](#parent-direction) shows
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

### Helper Methods for Nested Creation

Helper methods on the parent entity, such as `LineItem.add_note()` above, keep nested creation in one place:

```python
with domain.domain_context():
    item.add_note("Deliver after 5pm")
    item.add_customization("Size", "Large")
```

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

Keep the tree to two or three levels, such as Order, then LineItem, then LineItemNote. [Anti-patterns](anti-patterns.md) shows how to flatten a deeper one.

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

Loading an aggregate loads every entity in its tree:

```python
with domain.domain_context():
    repository = domain.repository_for(Order)
    repository.add(order)

    # If you have many line items with many notes each:
    order = repository.get(order.id)
    # This loads: Order + all LineItems + all Notes + all Customizations
```

## Testing

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

- [HasOne relationships](./with-hasone.md): One-to-one entity relationships
- [HasMany relationships](./with-hasmany.md): One-to-many entity relationships
- [Aggregates](../../aggregate/SKILL.md): Aggregate design patterns
