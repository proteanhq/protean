# Entity Anti-Patterns

This guide covers common mistakes when working with entities and how to avoid them.

## 1. Entity Without `part_of`

❌ **Wrong: Defining entity without aggregate association**

```python
@domain.entity
class Comment:
    content: String(max_length=500)
    author: String(max_length=100)
```

**Error:** `IncorrectUsageError` with the message `` Entity `Comment` needs to be associated with an Aggregate ``

✅ **Correct: Always specify the parent aggregate**

```python
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
# Get the aggregate first
post = domain.repository_for(Post).get(post_id)

# Access entities through the aggregate
comments = [c for c in post.comments if c.author == "John"]
```

**Why:** The aggregate is responsible for managing entity access and maintaining invariants.

---

## 3. Persisting Entities Directly

❌ **Wrong: Saving entities without their aggregate**

```python
comment = Comment(content="Great post!", author="John")
domain.repository_for(Comment).add(comment)  # Wrong!
```

**Problems:**
- Entities don't have their own repositories
- Breaks aggregate boundary
- Can lead to orphaned entities

✅ **Correct: Persist through the aggregate**

```python
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
@domain.entity(part_of="Order")
class Money:
    amount: Float(required=True)
    currency: String(required=True, max_length=3)
```

**Problems:**
- Money doesn't need identity
- Adds unnecessary complexity
- Two Money objects with same values should be equal

✅ **Correct: Use value object for data without identity**

```python
@domain.value_object
class Money:
    amount: Float(required=True)
    currency: String(required=True, max_length=3)

@domain.entity(part_of="Order")
class LineItem:
    product_id: String(required=True)
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
    product_id: String(required=True)
    quantity: Integer(required=True)
    related_items = HasMany("RelatedLineItem")

@domain.entity(part_of="Order")
class RelatedLineItem:
    product_id: String(required=True)
    relationship_type: String(required=True)  # "bundle", "addon", etc.
    # Automatic reference back to parent
    line_item = Reference(LineItem)
```

**Why:** Clear parent-child relationship is easier to understand and maintain.

---

## 6. Deep Entity Nesting (Too Many Levels)

❌ **Wrong: Creating deep hierarchies**

```python
Order → LineItem → Note → Reply → SubReply → Attachment  # 6 levels!
```

**Problems:**
- Hard to navigate
- Complex queries
- Performance issues
- Cognitive overload

✅ **Correct: Keep hierarchies shallow (2-3 levels max)**

```python
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
@domain.entity(part_of="Order")
class LineItem:
    quantity: Integer()  # No constraints!
    unit_price: Float()  # Can be negative!

    def set_quantity(self, qty):
        self.quantity = qty  # No validation!
```

**Problems:**
- Can create invalid state
- Business rules not enforced
- Data integrity issues

✅ **Correct: Validate in fields and methods**

```python
@domain.entity(part_of="Order")
class LineItem:
    quantity: Integer(required=True, min_value=1, max_value=9999)
    unit_price: Float(required=True, min_value=0.01)

    def set_quantity(self, qty: int):
        if qty < 1:
            raise ValueError("Quantity must be at least 1")
        if qty > 9999:
            raise ValueError("Quantity cannot exceed 9999")
        self.quantity = qty
```

**Why:** Validation ensures entities always maintain valid state.

---

## 8. Entity Referencing Another Aggregate

❌ **Wrong: Entity directly referencing another aggregate**

```python
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

✅ **Correct: Use IDs to reference other aggregates**

```python
@domain.aggregate
class Order:
    customer_id: String(required=True)  # Just the ID
    line_items = HasMany("LineItem")

@domain.entity(part_of="Order")
class LineItem:
    product_id: String(required=True)  # Just the ID, not the Product aggregate
    quantity: Integer(required=True)
```

**Why:** Aggregates should be loosely coupled; use IDs to reference other aggregates.

---

## 9. Anemic Entities (No Behavior)

❌ **Wrong: Entity with only data, no behavior**

```python
@domain.entity(part_of="Order")
class LineItem:
    product_id: String(required=True)
    quantity: Integer(required=True)
    unit_price: Float(required=True)
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
    product_id: String(required=True)
    quantity: Integer(required=True)
    unit_price: Float(required=True)
    discount_percent: Float(default=0.0)

    @property
    def subtotal(self) -> float:
        """Calculate line item subtotal."""
        return self.quantity * self.unit_price

    @property
    def discount_amount(self) -> float:
        """Calculate discount amount."""
        return self.subtotal * (self.discount_percent / 100.0)

    @property
    def total(self) -> float:
        """Calculate total after discount."""
        return self.subtotal - self.discount_amount

    def apply_discount(self, percent: float):
        """Apply discount with validation."""
        if percent < 0 or percent > 100:
            raise ValueError("Discount must be 0-100%")
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
@domain.entity(part_of="Order")
class LineItem:
    product_id: String(required=True)
    # Automatic fields added:
    # - order: Reference(Order)
    # - order_id: String()

# Usage
order = Order(customer_id="C123")
item = LineItem(product_id="P1", quantity=2)
order.add_line_items([item])

# Navigate back to parent
parent_order = item.order
parent_id = item.order_id
```

**Why:** Protean automatically creates bidirectional references for convenient navigation.

---

## 11. Ignoring `None` Collections

❌ **Wrong: Not checking for None before accessing collections**

```python
@domain.aggregate
class Order:
    line_items = HasMany("LineItem")

    @property
    def total(self) -> float:
        # This will crash if line_items is None!
        return sum(item.subtotal for item in self.line_items)
```

**Problems:**
- Runtime errors when collection is None
- Collections are None before entities are added

✅ **Correct: Always check for None**

```python
@domain.aggregate
class Order:
    line_items = HasMany("LineItem")

    @property
    def total(self) -> float:
        if not self.line_items:
            return 0.0
        return sum(item.subtotal for item in self.line_items)

    @property
    def item_count(self) -> int:
        return len(self.line_items) if self.line_items else 0
```

**Why:** HasMany and HasOne collections can be None before entities are added.

---

## 12. Using Entities in Different Aggregates

❌ **Wrong: Reusing entity class across aggregates**

```python
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
| Ignoring None collections | Always check before iterating |
| Reusing entities across aggregates | Use value objects for shared concepts |

## Related

- [Entity basics](../SKILL.md) - Core entity concepts
- [Aggregate patterns](../../aggregate/references/anti-patterns.md) - Aggregate anti-patterns
- [Value objects](../../value-object/SKILL.md) - When to use value objects
