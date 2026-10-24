# Entity Anti-Patterns

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

---

## 2. Querying Entities Directly

❌ **Wrong: Accessing entities through their own repository**

```python
# fragment
# Don't do this
comment_repo = domain.repository_for(Comment)
comments = comment_repo.filter(author="John")
```

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

---

## 3. Persisting Entities Directly

❌ **Wrong: Saving entities without their aggregate**

```python
# fragment
comment = Comment(content="Great post!", author="John")
domain.repository_for(Comment).add(comment)  # Wrong!
```

`domain.repository_for(Comment)` does return a repository, and `add()` saves the comment with no post.

✅ **Correct: Persist through the aggregate**

```python
with domain.domain_context():
    post = domain.repository_for(Post).get(post_id)
    comment = Comment(content="Great post!", author="John")
    post.add_comments([comment])
    domain.repository_for(Post).add(post)
```

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

---

## 6. Deep Entity Nesting (Too Many Levels)

❌ **Wrong: Creating deep hierarchies**

```python
# fragment
Order → LineItem → Note → Reply → SubReply → Attachment  # 6 levels!
```

✅ **Correct: Keep hierarchies shallow (2-3 levels max)**

```python
# fragment
# Better: Limit depth
Order → LineItem → Note  # 3 levels

# Or: Flatten structure
Order → LineItem
Order → Note (holding the LineItem's id in an Identifier field)
```

---

## 7. Missing Validation in Entities

❌ **Wrong: No validation on entity fields or methods**

```python
# fragment
@domain.entity(part_of="Order")
class LineItem:
    quantity: Integer()  # No constraints!
    unit_price: Decimal(precision=19, scale=4)  # Can be negative!

    def set_quantity(self, qty):
        self.quantity = qty  # No validation!
```

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

`protean check` reports it as `CROSS_AGGREGATE_REFERENCE`. A `Reference` field is only for an entity pointing at its parent: the aggregate root, or the parent entity when the entity is nested.

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
        """Calculate discount amount, rounded to the money fields' scale."""
        return (self.subtotal * D(str(self.discount_percent)) / 100).quantize(D("0.0001"))

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

---

## 10. Assuming a HasOne Is Always Set

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

A `HasOne` field is `None` until an entity is assigned, so the error shows up only for orders without one.

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

---

## 11. Using Entities in Different Aggregates

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

An entity class belongs to one aggregate only.

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

---

## Related

- [Entity basics](../SKILL.md): Core entity concepts
- [Aggregate patterns](../../aggregate/references/anti-patterns.md): Aggregate anti-patterns
- [Value objects](../../value-object/SKILL.md): When to use value objects
