---
name: entity
description: Define a Protean entity - a domain object with unique identity that is part of an aggregate. Entities are similar to aggregates but don't manage their own persistence - they're always accessed through their parent aggregate. Use when adding objects with identity to an existing aggregate, when modeling concepts that have identity but are not standalone (like LineItem in Order, Comment in Post), when the user asks to "add an entity", "create a child object", or when they describe a concept that has identity but must be part of a larger aggregate. Entities cannot exist independently and are always persisted through their aggregate.
license: Apache-2.0
compatibility: Requires Python 3.11+, protean framework
metadata:
  author: proteanhq
  version: "0.1"
  category: element
---

# Entity

## Basic structure

An entity is defined using the `@domain.entity` decorator and must specify which aggregate it belongs to:

```python
from protean import Domain
from protean.fields import Decimal, HasMany, Identifier, Integer

domain = Domain()

@domain.aggregate
class Order:
    customer_id: Identifier(required=True)
    line_items = HasMany("LineItem")

@domain.entity(part_of="Order")
class LineItem:
    product_id: Identifier(required=True)
    quantity: Integer(required=True, min_value=1)
    unit_price: Decimal(precision=19, scale=4, required=True)
```

`customer_id` and `product_id` hold the ids of other aggregates. Link to another aggregate with an `Identifier` field, never with a `Reference`.

## Key rules

1. **Entities must be part of an aggregate** - Use `part_of` parameter to associate with parent aggregate. **Use a string reference** (`part_of="Order"`) to avoid circular dependencies when aggregate and entity are in the same file. A nested entity passes its parent entity as a class (`part_of=LineItem`), because a string resolves only to an aggregate
2. **Entities have automatic identity** - An `id` field is auto-generated unless `auto_add_id_field=False`
3. **Entities get automatic reference fields** - A reference field back to parent aggregate is created automatically
4. **Entities are accessed through aggregates** - Never query or update entities directly
5. **Entities are persisted with aggregates** - They use the same persistence store as their parent
6. **Entities can contain other entities** - Via `HasOne` or `HasMany` relationships
7. **Entities cannot be root elements** - They must always be part of an aggregate
8. **Entities are mutable** - Their state can change while maintaining identity

## Defining entities

### Simple entity

```python
from protean.fields import String

@domain.aggregate
class Post:
    title: String(required=True, max_length=200)
    comments = HasMany("Comment")

@domain.entity(part_of="Post")
class Comment:
    content: String(required=True, max_length=500)
    author: String(required=True, max_length=100)
    # Automatically gets: id field
    # Automatically gets: post = Reference(Post)
    # Automatically gets: post_id  # Shadow field holding the post's id
```

### Entity with part_of

**Use a string reference to the aggregate** for `part_of` to avoid circular dependencies (a nested entity is the exception, see [Nested entities](references/nested-entities.md)):

```python
@domain.entity(part_of="Order")
class LineItem:
    product_id: String(required=True)
    quantity: Integer(required=True)
```

**Why string references?** Aggregates, entities, and value objects are often defined in the same file. The aggregate references entities via `HasMany("LineItem")` (forward reference), and entities reference back via `part_of`. If entities use a class reference (`part_of=Order`), the entity must be defined *after* the aggregate, but the aggregate's `HasMany` needs the entity to exist too. Using string references on both sides (`HasMany("LineItem")` and `part_of="Order"`) breaks this circular dependency and allows elements to be defined in any order.

## Associations

### HasOne relationship

One-to-one relationship with another entity:

```python
@domain.aggregate
class Order:
    customer_id: Identifier(required=True)
    shipping_info = HasOne("ShippingInfo")

@domain.entity(part_of="Order")
class ShippingInfo:
    address: String(required=True, max_length=500)
    city: String(required=True, max_length=100)
```

**Note**: For `HasOne` relationships, access the related entity directly through the field (e.g., `order.shipping_info`). No special helper methods are needed.

### HasMany relationship

One-to-many relationship with other entities:

```python
@domain.aggregate
class Order:
    customer_id: Identifier(required=True)
    shipping_info = HasOne("ShippingInfo")
    line_items = HasMany("LineItem")

@domain.entity(part_of="Order")
class LineItem:
    product_id: Identifier(required=True)
    quantity: Integer(required=True)
```

**Auto-generated helper methods**: When you define a `HasMany` field on an aggregate or entity, Protean automatically creates helper methods for managing the association. For the `line_items` field above, these methods are generated:

- `add_line_items(item)` - Add one or more items to the collection
- `remove_line_items(item)` - Remove an item from the collection
- `get_one_from_line_items(id=item_id)` - Get the one item that matches the keyword arguments. It raises `ObjectNotFoundError` (from `protean.exceptions`) when no item matches, and `TooManyObjectsError` when more than one does.
- `filter_line_items(**criteria)` - Return the items whose fields equal the given values, such as `filter_line_items(product_id="P1")`. It matches on equality only.

**Important**: Do NOT manually create these methods - they are automatically available. Only create custom methods if you need behavior different from the defaults.

### Automatic reference fields

Entities automatically get a reference field to their parent aggregate. A `LineItem` that is part of `Order` gets `item.order`, which returns the `Order` object, and `item.order_id`, which holds the order's id. [Accessing entities](#accessing-entities) shows both in use.

## Configuration options

### Sharing fields through a base class

`@domain.entity` has no `abstract` option. To share fields between entities, put them on a plain subclass of `BaseEntity` and leave it undecorated. Decorate only the concrete subclasses. Keep association fields (`HasMany`, `HasOne`) on the concrete entities, because two entities that inherit the same association fail `domain.init()`:

```python
from protean.core.entity import BaseEntity

class BaseLineItem(BaseEntity):
    quantity: Integer(required=True)

@domain.entity(part_of="Order")
class ProductLineItem(BaseLineItem):
    product_id: Identifier(required=True)
    # Inherits quantity from BaseLineItem
```

The base class is not registered with the domain, so it gets no table and no association. Do not decorate it: a decorated base becomes a real entity of its own.

### `auto_add_id_field`

Control automatic ID field generation:

```python
@domain.entity(part_of="Order", auto_add_id_field=False)
class LineItem:
    # You must provide your own identifier field
    line_number: Integer(required=True, identifier=True)
    product_id: Identifier(required=True)
```

### `schema_name`

Customize the persistence name:

```python
@domain.entity(part_of="Order", schema_name="order_items")
class LineItem:
    product_id: Identifier(required=True)
    quantity: Integer(required=True)
```

## Working with entities

Creating instances needs an initialized domain and an active domain context, so the examples call `domain.init(traverse=False)` once and wrap their code in `with domain.domain_context():`. They use auto-generated helper methods like `add_line_items()` and `remove_line_items()`. These are automatically created by Protean for `HasMany` relationships - you don't need to define them yourself. They work on this model:

```python
@domain.aggregate
class Order:
    customer_id: Identifier(required=True)
    line_items = HasMany("LineItem")

@domain.entity(part_of="Order")
class LineItem:
    product_id: Identifier(required=True)
    quantity: Integer(required=True)
```

### Adding entities to aggregate

```python
domain.init(traverse=False)

with domain.domain_context():
    order = Order(customer_id="C123")

    # Create and add entity using auto-generated add_line_items() helper
    item = LineItem(product_id="P1", quantity=2)
    order.add_line_items([item])

    # Or add multiple
    items = [
        LineItem(product_id="P2", quantity=1),
        LineItem(product_id="P3", quantity=4),
    ]
    order.add_line_items(items)

    domain.repository_for(Order).add(order)
    order_id = order.id
```

### Accessing entities

```python
with domain.domain_context():
    # Access via aggregate
    order = domain.repository_for(Order).get(order_id)
    line_items = order.line_items  # List of LineItem entities

    # Iterate over entities
    for item in order.line_items:
        print(f"Product: {item.product_id}, Qty: {item.quantity}")

    # Access the parent from an entity
    parent_order = item.order  # Returns the Order object
    parent_id = item.order_id  # Returns the order's ID
```

### Updating entities

```python
with domain.domain_context():
    # Update through aggregate
    order = domain.repository_for(Order).get(order_id)
    order.line_items[0].quantity = 5  # Update entity
    domain.repository_for(Order).add(order)  # Save aggregate
```

### Removing entities

```python
with domain.domain_context():
    order = domain.repository_for(Order).get(order_id)
    item = order.line_items[0]
    order.remove_line_items(item)  # Uses auto-generated remove_line_items() helper
    domain.repository_for(Order).add(order)  # Save aggregate
```

## Entity behavior

### Methods and properties

Entities can have methods and computed properties:

```python
from decimal import Decimal as D  # stdlib Decimal, aliased so it does not clash with the field

@domain.entity(part_of="Order")
class LineItem:
    product_id: Identifier(required=True)
    quantity: Integer(required=True, min_value=1)
    unit_price: Decimal(precision=19, scale=4, required=True)

    @property
    def subtotal(self) -> D:
        """Calculate line item subtotal."""
        return self.quantity * self.unit_price

    def increase_quantity(self, amount: int):
        """Increase quantity by specified amount."""
        if amount <= 0:
            raise ValueError("Amount must be positive")
        self.quantity += amount
```

### Validation and invariants

Entities support three levels of validation (use in this order):

**1. Field-level constraints** - For data type validations and simple constraints:

**Important**: Always define data type validations at the field level using built-in parameters. Never validate these manually in methods.

```python
@domain.entity(part_of="Order")
class LineItem:
    product_id: String(required=True, max_length=50, min_length=3)
    quantity: Integer(required=True, min_value=1, max_value=1000)
    unit_price: Decimal(precision=19, scale=4, required=True, min_value=0.01)
    discount_percent: Float(min_value=0.0, max_value=100.0, default=0.0)
```

**Common field validation parameters**:
- **All fields**: `required`, `default`, `unique`, `choices`, `validators`
- **String**: `max_length`, `min_length`, `sanitize`
- **Integer/Float/Decimal**: `min_value`, `max_value`
- **Decimal**: `precision`, `scale` (use `Decimal(precision=19, scale=4)` for money)

**2. Business rules as invariants** - For cross-field validations and domain logic:

**Important**: All business validations should be codified as invariants, as granularly as possible. Each invariant should check a single business rule.

```python
from protean import invariant
from protean.exceptions import ValidationError

@domain.entity(part_of="Order")
class LineItem:
    product_id: String(required=True, max_length=50)
    quantity: Integer(required=True, min_value=1)
    unit_price: Decimal(precision=19, scale=4, required=True, min_value=0.01)
    discount_percent: Float(min_value=0.0, max_value=100.0, default=0.0)

    @invariant.post
    def large_discount_needs_bulk_quantity(self):
        """Granular business rule: discounts above 20% need 10 or more units.

        Post invariants run at the end of __init__ and on every field assignment.
        """
        if self.discount_percent > 20 and self.quantity < 10:
            raise ValidationError(
                {"_entity": ["Discounts above 20% need a quantity of 10 or more"]}
            )

    @invariant.post
    def quantity_times_price_must_be_reasonable(self):
        """Granular business rule: total price sanity check.

        Keep each invariant focused on ONE business constraint.
        """
        total = self.quantity * self.unit_price
        if total > 1_000_000:  # Business limit
            raise ValidationError(
                {"_entity": ["Line item total exceeds maximum allowed"]}
            )

    @property
    def subtotal(self) -> D:
        """Calculate line item subtotal."""
        base = self.quantity * self.unit_price
        discount = base * D(str(self.discount_percent)) / 100
        return base - discount
```

**Note**: Entity invariants are validated as part of the aggregate's validation. Post-invariants run at the end of `__init__` and on every field assignment. A change to a child entity also runs the aggregate root's post-invariants. `repository.add()` does not check them again, so an invalid change fails at the assignment, not at save time.

## Common mistakes

❌ **Defining entity without `part_of`**
```python
# fragment
@domain.entity
class Comment:  # Error: Entity needs to be associated with an Aggregate
    content: String(max_length=500)
```

✅ **Always specify parent aggregate**:
```python
@domain.entity(part_of="Post")
class Comment:
    content: String(max_length=500)
    author: String(max_length=100)
```

---

❌ **Querying entities directly**
```python
# fragment
# Don't do this
comments = domain.repository_for(Comment).filter(author="John")
```

✅ **Access through aggregate**:
```python
@domain.aggregate
class Post:
    title: String(required=True, max_length=200)
    comments = HasMany("Comment")

@domain.entity(part_of="Post")
class Comment:
    content: String(max_length=500)
    author: String(max_length=100)

domain.init(traverse=False)

with domain.domain_context():
    post = Post(title="Hello", comments=[Comment(content="Nice", author="John")])
    domain.repository_for(Post).add(post)

    post = domain.repository_for(Post).get(post.id)
    comments = post.filter_comments(author="John")
```

---

❌ **Entity containing another entity without relationship**
```python
# fragment
@domain.entity(part_of="Order")
class LineItem:
    note = Comment()  # Wrong: Use HasOne relationship
```

✅ **Use proper association fields**:
```python
@domain.aggregate
class Order:
    customer_id: Identifier(required=True)
    line_items = HasMany("LineItem")

@domain.entity(part_of="Order")
class LineItem:
    product_id: Identifier(required=True)
    quantity: Integer(required=True)
    notes = HasMany("LineItemNote")

@domain.entity(part_of=LineItem)
class LineItemNote:
    content: String(max_length=500)
```

A nested entity is `part_of` its parent entity, not the aggregate. Pass the parent entity as a class: a string `part_of` resolves only to an aggregate.

---

❌ **Using entity as aggregate root**
```python
# fragment
@domain.entity(part_of="Order")
class LineItem:
    product_id: String(required=True)

# Don't persist entities directly
domain.repository_for(LineItem).add(item)  # Wrong!
```

✅ **Persist through aggregate**:
```python
domain.init(traverse=False)

with domain.domain_context():
    order = Order(customer_id="C123")
    order.add_line_items([LineItem(product_id="P1", quantity=2)])
    domain.repository_for(Order).add(order)  # Correct!
```

---

❌ **Manually creating auto-generated helper methods**
```python
# fragment
@domain.aggregate
class Order:
    line_items = HasMany("LineItem")

    # Don't do this - method is already auto-generated!
    def add_line_items(self, items):
        """Manually defined helper."""
        ...
```

✅ **Use auto-generated helpers directly**:
```python
@domain.aggregate
class Order:
    customer_id: Identifier(required=True)
    line_items = HasMany("LineItem")
    # add_line_items(), remove_line_items(), etc. are auto-generated!

@domain.entity(part_of="Order")
class LineItem:
    product_id: Identifier(required=True)
    quantity: Integer(required=True)

domain.init(traverse=False)

# Use the auto-generated helpers
with domain.domain_context():
    order = Order(customer_id="C123")
    order.add_line_items([LineItem(product_id="P1", quantity=2)])  # Auto-generated
```

## Examples

- [Simple entity](assets/entity_simple.py): a minimal entity inside an aggregate

## Detailed references

- [HasOne relationships](references/with-hasone.md) - One-to-one entity relationships
- [HasMany relationships](references/with-hasmany.md) - One-to-many entity relationships
- [Nested entities](references/nested-entities.md) - Entities containing other entities
- [Configuration options](references/configuration.md) - Entity configuration and customization
- [Anti-patterns](references/anti-patterns.md) - Common mistakes and how to avoid them

## Related skills

- [aggregate](../aggregate/SKILL.md) - Learn about aggregates that contain entities
- [value-object](../value-object/SKILL.md) - When to use value objects instead of entities

## Verify your work

- [Verify with check](../../references/verify-with-check.md): run `check` and resolve what it reports
