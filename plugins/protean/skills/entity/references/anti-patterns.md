# Entity Anti-Patterns

This guide covers common mistakes when working with entities and how to avoid them.

## 1. Entity Without `part_of`

❌ **Wrong: Defining entity without aggregate association**

```python
# fragment
@domain.entity
class Comment:
    content: String(max_length=500)
    author: String(max_length=100)
```

**Error:** `IncorrectUsageError` with the message `` Entity `Comment` needs to be associated with an Aggregate ``

✅ **Correct: Always specify the parent aggregate**

```python
from decimal import Decimal as D  # stdlib Decimal, aliased so it does not clash with the field

from protean import Domain
from protean.fields import (
    Decimal, Float, HasMany, HasOne, Identifier, Integer, String, ValueObject,
)

domain = Domain()

@domain.aggregate
class Post:
    title: String(required=True, max_length=200)
    comments = HasMany("Comment")

@domain.entity(part_of="Post")
class Comment:
    content: String(max_length=500)
    author: String(max_length=100)
```

**Why:** Entities cannot exist independently; they must belong to an aggregate that manages their lifecycle.

---

## 2. Querying Entities Directly

❌ **Wrong: Accessing entities through their own repository**

```python
# fragment
# Don't do this
comment_repo = domain.repository_for(Comment)
comments = comment_repo.filter(author="John")
```

**Problems:**
- Bypasses aggregate boundary
- Can violate business invariants
- Not how Protean is designed to work

✅ **Correct: Access entities through their aggregate**

```python
domain.init(traverse=False)

with domain.domain_context():
    post = Post(title="Hello", comments=[Comment(content="Nice", author="John")])
    domain.repository_for(Post).add(post)
    post_id = post.id

    # Get the aggregate first
    post = domain.repository_for(Post).get(post_id)

    # Access entities through the aggregate
    comments = post.filter_comments(author="John")
```

**Why:** The aggregate is responsible for managing entity access and maintaining invariants.

---

## 3. Persisting Entities Directly

❌ **Wrong: Saving entities without their aggregate**

```python
# fragment
comment = Comment(content="Great post!", author="John")
domain.repository_for(Comment).add(comment)  # Wrong!
```

**Problems:**
- Entities don't have their own repositories
- Breaks aggregate boundary
- Can lead to orphaned entities

✅ **Correct: Persist through the aggregate**

```python
with domain.domain_context():
    post = domain.repository_for(Post).get(post_id)
    comment = Comment(content="Great post!", author="John")
    post.add_comments([comment])
    domain.repository_for(Post).add(post)
```

**Why:** Entities are always persisted as part of their aggregate.

---

## 4. Using Entity When Value Object is Better

❌ **Wrong: Creating entity for data without identity**

```python
# fragment
@domain.entity(part_of="Order")
class Money:
    amount: Decimal(precision=19, scale=4, required=True)
    currency: String(required=True, max_length=3)
```

**Problems:**
- Money doesn't need identity
- Adds unnecessary complexity
- Two Money objects with same values should be equal

✅ **Correct: Use value object for data without identity**

```python
@domain.aggregate
class Order:
    customer_id: Identifier(required=True)
    line_items = HasMany("LineItem")

@domain.value_object
class Money:
    amount: Decimal(precision=19, scale=4, required=True)
    currency: String(required=True, max_length=3)

@domain.entity(part_of="Order")
class LineItem:
    product_id: Identifier(required=True)
    quantity: Integer(required=True)
    unit_price = ValueObject(Money, required=True)
```

**Why:** Value objects are immutable and compared by value, which is appropriate for money.

**When to use Entity vs Value Object:**
- Entity: Has identity, mutable, lifecycle matters (LineItem, Comment, Address that can be updated)
- Value Object: No identity, immutable, only value matters (Money, DateRange, Coordinates)

---

## 5. Circular References Between Entities

❌ **Wrong: Creating circular dependencies**

```python
# fragment
@domain.entity(part_of="Order")
class LineItem:
    related_item = Reference("RelatedLineItem")

@domain.entity(part_of="Order")
class RelatedLineItem:
    parent_item = Reference(LineItem)
```

**Problems:**
- Confusing navigation
- Hard to maintain
- Can cause infinite loops

✅ **Correct: Use HasMany for collections or rethink the relationship**

```python
@domain.entity(part_of="Order")
class LineItem:
    product_id: Identifier(required=True)
    quantity: Integer(required=True)
    related_items = HasMany("RelatedLineItem")

@domain.entity(part_of=LineItem)
class RelatedLineItem:
    product_id: Identifier(required=True)
    relationship_type: String(required=True)  # "bundle", "addon", etc.
    # Automatically gets line_item = Reference(LineItem) back to its parent
```

`RelatedLineItem` is `part_of` its parent entity, passed as a class. Protean adds the `line_item` reference and `line_item_id` field on its own.

**Why:** Clear parent-child relationship is easier to understand and maintain.

---

## 6. Deep Entity Nesting (Too Many Levels)

❌ **Wrong: Creating deep hierarchies**

```python
# fragment
Order → LineItem → Note → Reply → SubReply → Attachment  # 6 levels!
```

**Problems:**
- Hard to navigate
- Complex queries
- Performance issues
- Cognitive overload

✅ **Correct: Keep hierarchies shallow (2-3 levels max)**

```python
# fragment
# Better: Limit depth
Order → LineItem → Note  # 3 levels

# Or: Flatten structure
Order → LineItem
Order → Note (with reference to LineItem)
```

**Why:** Shallow hierarchies are easier to understand, maintain, and query efficiently.

---

## 7. Missing Validation in Entities

❌ **Wrong: No validation on entity fields or methods**

```python
# fragment
@domain.entity(part_of="Order")
class LineItem:
    quantity: Integer()  # No constraints!
    unit_price: Decimal()  # Can be negative!

    def set_quantity(self, qty):
        self.quantity = qty  # No validation!
```

**Problems:**
- Can create invalid state
- Business rules not enforced
- Data integrity issues

✅ **Correct: Put constraints on the fields**

```python
@domain.entity(part_of="Order")
class LineItem:
    quantity: Integer(required=True, min_value=1, max_value=9999)
    unit_price: Decimal(precision=19, scale=4, required=True, min_value=0.01)

    def set_quantity(self, qty: int):
        # The field constraints reject 0 or 10000 with a ValidationError
        self.quantity = qty
```

**Why:** Field constraints run on every assignment, so the entity cannot hold an invalid value. Rules that span several fields belong in invariants.

---

## 8. Entity Referencing Another Aggregate

❌ **Wrong: Entity directly referencing another aggregate**

```python
# fragment
@domain.aggregate
class Customer:
    name: String(required=True)

@domain.entity(part_of="Order")
class LineItem:
    customer = Reference(Customer)  # Wrong!
```

**Problems:**
- Violates aggregate boundary
- Creates tight coupling
- Can lead to consistency issues
- `protean check` reports it as `CROSS_AGGREGATE_REFERENCE`

A `Reference` field is only for an entity pointing at its own aggregate root.

✅ **Correct: Use IDs to reference other aggregates**

```python
@domain.aggregate
class Order:
    customer_id: Identifier(required=True)  # Just the ID
    line_items = HasMany("LineItem")

@domain.entity(part_of="Order")
class LineItem:
    product_id: Identifier(required=True)  # Just the ID, not the Product aggregate
    quantity: Integer(required=True)
```

**Why:** Aggregates should be loosely coupled; use IDs to reference other aggregates.

---

## 9. Anemic Entities (No Behavior)

❌ **Wrong: Entity with only data, no behavior**

```python
# fragment
@domain.entity(part_of="Order")
class LineItem:
    product_id: Identifier(required=True)
    quantity: Integer(required=True)
    unit_price: Decimal(precision=19, scale=4, required=True)
    # No methods, no computed properties, just data
```

**Problems:**
- Business logic ends up elsewhere (aggregate or service)
- Entity is just a data bag
- Violates object-oriented principles

✅ **Correct: Add behavior to entities**

```python
@domain.entity(part_of="Order")
class LineItem:
    product_id: Identifier(required=True)
    quantity: Integer(required=True, min_value=1)
    unit_price: Decimal(precision=19, scale=4, required=True)
    discount_percent: Float(default=0.0, min_value=0.0, max_value=100.0)

    @property
    def subtotal(self) -> D:
        """Calculate line item subtotal."""
        return self.quantity * self.unit_price

    @property
    def discount_amount(self) -> D:
        """Calculate discount amount."""
        return self.subtotal * D(str(self.discount_percent)) / 100

    @property
    def total(self) -> D:
        """Calculate total after discount."""
        return self.subtotal - self.discount_amount

    def apply_discount(self, percent: float):
        """Apply a discount. The field rejects values outside 0-100."""
        self.discount_percent = percent

    def increase_quantity(self, amount: int):
        """Increase quantity with validation."""
        if amount <= 0:
            raise ValueError("Amount must be positive")
        self.quantity += amount
```

**Why:** Entities should encapsulate both data and behavior related to that data.

---

## 10. Forgetting Bidirectional References

❌ **Wrong: Not utilizing automatic parent references**

```python
# fragment
# Trying to navigate from entity to parent manually
for item in order.line_items:
    # How do I get back to the order?
    # No reference stored!
    pass
```

**Problems:**
- Can't navigate back to parent
- Have to pass parent around manually
- Loses context

✅ **Correct: Use automatic reference fields**

```python
@domain.aggregate
class Order:
    customer_id: Identifier(required=True)
    line_items = HasMany("LineItem")

@domain.entity(part_of="Order")
class LineItem:
    product_id: Identifier(required=True)
    quantity: Integer(required=True)
    # Automatic fields added:
    # - order: Reference(Order)
    # - order_id: the order's id

domain.init(traverse=False)

# Usage
with domain.domain_context():
    order = Order(customer_id="C123")
    item = LineItem(product_id="P1", quantity=2)
    order.add_line_items([item])

    # Navigate back to parent
    parent_order = item.order
    parent_id = item.order_id
```

**Why:** Protean automatically creates bidirectional references for convenient navigation.

---

## 11. Assuming a HasOne Is Always Set

❌ **Wrong: Reading through a HasOne without checking for None**

```python
# fragment
@domain.aggregate
class Order:
    line_items = HasMany("LineItem")
    shipping_info = HasOne("ShippingInfo")

    @property
    def shipping_city(self) -> str:
        # Raises AttributeError when no ShippingInfo has been set
        return self.shipping_info.city
```

**Problems:**
- A `HasOne` field is `None` until an entity is assigned
- The error shows up only for orders without the child entity

✅ **Correct: Check the HasOne for None; iterate a HasMany directly**

```python
@domain.aggregate
class Order:
    customer_id: Identifier(required=True)
    line_items = HasMany("LineItem")
    shipping_info = HasOne("ShippingInfo")

    @property
    def total(self) -> D:
        # A HasMany field is an empty list when there are no items, never None
        return sum((item.total for item in self.line_items), D("0"))

    @property
    def shipping_city(self) -> str | None:
        if self.shipping_info is None:
            return None
        return self.shipping_info.city

@domain.entity(part_of="Order")
class ShippingInfo:
    city: String(required=True, max_length=100)
```

**Why:** A `HasOne` field is `None` until an entity is assigned. A `HasMany` field is always a list, empty when there are no items.

---

## 12. Using Entities in Different Aggregates

❌ **Wrong: Reusing entity class across aggregates**

```python
# fragment
@domain.entity(part_of="Order")
class Address:
    street: String(required=True)
    city: String(required=True)

@domain.aggregate
class Customer:
    # Can't use the same Address entity!
    # It's already part of Order
    billing_address = HasOne(Address)  # Error!
```

**Problems:**
- Entity can only belong to one aggregate
- Shared entities violate aggregate boundaries

✅ **Correct: Use value objects for shared concepts**

```python
@domain.value_object
class Address:
    """Reusable address value object."""
    street: String(required=True)
    city: String(required=True)
    postal_code: String(required=True)

@domain.aggregate
class Order:
    shipping_address = ValueObject(Address, required=True)

@domain.aggregate
class Customer:
    billing_address = ValueObject(Address, required=True)
```

**Why:** Value objects can be reused across aggregates; entities cannot.

---

## Summary: Quick Reference

| Anti-Pattern | Correct Approach |
|-------------|------------------|
| Entity without `part_of` | Always specify parent aggregate |
| Querying entities directly | Access through aggregate |
| Persisting entities directly | Persist through aggregate |
| Entity for data without identity | Use value object instead |
| Circular entity references | Use clear parent-child HasMany |
| Deep nesting (5+ levels) | Limit to 2-3 levels |
| No validation | Validate in fields and methods |
| Entity referencing aggregate | Use IDs, not references |
| Anemic entities | Add behavior and computed properties |
| Assuming a HasOne is set | Check it for None; a HasMany is always a list |
| Reusing entities across aggregates | Use value objects for shared concepts |

## Related

- [Entity basics](../SKILL.md) - Core entity concepts
- [Aggregate patterns](../../aggregate/references/anti-patterns.md) - Aggregate anti-patterns
- [Value objects](../../value-object/SKILL.md) - When to use value objects
