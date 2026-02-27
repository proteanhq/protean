# Expressing Relationships

<span class="pathway-tag pathway-tag-ddd">DDD</span> <span class="pathway-tag pathway-tag-cqrs">CQRS</span> <span class="pathway-tag pathway-tag-es">ES</span>

!!!note "Relationships live inside aggregate boundaries"
    In DDD, associations (`HasOne`, `HasMany`, `Reference`) only connect
    objects *within the same aggregate cluster*. Aggregates never hold
    direct object references to other aggregates — they reference each
    other by identity. This rule keeps transaction boundaries clean and
    prevents hidden coupling between independently consistent clusters.

    See [Cross-Aggregate References](#cross-aggregate-references) for the
    identity-based pattern.

Protean provides a relationship system for modeling associations between
domain entities within an aggregate cluster. Relationships are expressed
through association fields (`HasOne`, `HasMany`) and their corresponding
reference fields (`Reference`), which work together to establish
bidirectional linkages.

## Relationship Types

### One-to-One (HasOne)

A `HasOne` relationship represents a one-to-one association between an aggregate and a child entity. The aggregate can have at most one instance of the related entity.

```python
@domain.aggregate
class Blog:
    title: String(max_length=100)
    settings = HasOne("BlogSettings")

@domain.entity(part_of=Blog)
class BlogSettings:
    theme: String(max_length=50)
    allow_comments: Boolean(default=True)
```

### One-to-Many (HasMany)

A `HasMany` relationship represents a one-to-many association where an aggregate can contain multiple instances of a child entity.

```python
@domain.aggregate
class Post:
    title: String(max_length=100)
    comments = HasMany("Comment")

@domain.entity(part_of=Post)
class Comment:
    content: String(max_length=500)
    author: String(max_length=50)
```

### Value Object Embedding

Value objects are embedded using the `ValueObject` field type, not
`HasOne`/`HasMany`. Unlike entity associations, value objects are stored
inline with the parent — they don't have their own identity or separate
table.

```python
@domain.value_object
class Address:
    street: String(max_length=200)
    city: String(max_length=100)
    zip_code: String(max_length=10)

@domain.aggregate
class Customer:
    name: String(max_length=100)
    billing_address = ValueObject(Address)
```

See the [Value Objects](./value-objects.md) guide for details on embedding
and initialization.

## Reference Fields

Every association automatically creates a corresponding `Reference` field in the child entity that points back to the parent aggregate. This establishes the inverse relationship and provides access to the parent from the child.

### Automatic Reference Creation

Protean automatically adds a `Reference` field to entities based on the aggregate they belong to:

```python
# After registration, Comment automatically gets:
# post = Reference(Post)  # Field name derived from aggregate name
# post_id = String()      # Shadow field for the foreign key
```

### Explicit Reference Fields

You can explicitly define reference fields for more control:

```python
@domain.entity(part_of=Post)
class Comment:
    content: String(max_length=500)
    post = Reference(Post)  # Explicit reference field
```

### Shadow Fields

Reference fields automatically create shadow fields (foreign key attributes) that store the actual identifier values:

- `Reference` field: `comment.post` → Contains the Post object
- Shadow field: `comment.post_id` → Contains the Post's ID value

## Customizing Relationships

### The `via` Parameter

The `via` parameter allows you to specify which field in the child entity should be used as the foreign key, instead of the default naming convention:

```python
@domain.aggregate
class Product:
    name: String(max_length=100)
    sku: String(identifier=True, max_length=20)
    reviews = HasMany("Review", via="product_sku")

@domain.entity(part_of=Product)
class Review:
    content: String(max_length=1000)
    rating: Integer(min_value=1, max_value=5)
    product_sku: String()  # Custom foreign key field
```

Without `via`, the foreign key would be `product_id`. With `via="product_sku"`, it uses `product_sku` instead.

### The `referenced_as` Parameter

The `referenced_as` parameter in Reference fields allows you to specify a custom name for the shadow field:

```python
@domain.entity(part_of=Order)
class OrderItem:
    product_name: String(max_length=100)
    order = Reference(Order, referenced_as="order_number")
    # Creates shadow field named 'order_number' instead of 'order_id'
```

When using both `via` and `referenced_as`, they must agree: the `via`
value on the `HasOne`/`HasMany` side should match the `referenced_as`
value on the `Reference` side so both ends resolve to the same field.

## Auto-Generated Helper Methods

For `HasMany` associations, Protean automatically generates helper methods
on the parent object. Given a field named `comments`, the following methods
are created:

| Method | Behavior |
|---|---|
| `add_comments(item_or_list)` | Append one or more entities to the collection |
| `remove_comments(item_or_list)` | Remove one or more entities from the collection |
| `get_one_from_comments(**kwargs)` | Return a single entity matching the criteria (raises if zero or multiple matches) |
| `filter_comments(**kwargs)` | Return all entities matching the criteria |

The method names are derived from the field name: `add_<field>`,
`remove_<field>`, `get_one_from_<field>`, `filter_<field>`.

```python
post = Post(title="New Post")

# Add comments
post.add_comments(Comment(content="First comment", author="alice"))
post.add_comments([
    Comment(content="Second comment", author="bob"),
    Comment(content="Third comment", author="alice"),
])

# Query within the collection
alice_comments = post.filter_comments(author="alice")
bob_comment = post.get_one_from_comments(author="bob")

# Remove
post.remove_comments(bob_comment)
```

!!!note
    `HasOne` fields do not generate helper methods — assign directly
    (e.g. `blog.settings = BlogSettings(...)`).

## Bidirectional Navigation

Relationships in Protean are bidirectional, allowing navigation in both directions:

```python
# From parent to child
post = Post(title="My Post")
comments = post.comments  # List of Comment objects

# From child to parent
comment = Comment(content="Great post!")
post = comment.post  # Post object
post_id = comment.post_id  # Post's ID value
```

## Dictionary Assignment

You can assign a plain dictionary where an entity or value object is
expected. Protean will automatically convert it:

```python
post.stats = {"likes": 10, "dislikes": 1}
# Equivalent to: post.stats = Statistic(likes=10, dislikes=1)
```

This also works during aggregate initialization for nested structures.

## Association Constraints

All association fields (`HasOne`, `HasMany`, `Reference`) are implicitly
optional — Protean sets `required=False` on them internally. There is
currently no way to make an association required at the field level; enforce
mandatory children through aggregate invariants instead:

```python
@domain.aggregate
class Order:
    items = HasMany("OrderItem")

    @invariant.post
    def must_have_at_least_one_item(self):
        if not self.items:
            raise ValidationError({"items": ["Order must have at least one item"]})
```

## Cross-Aggregate References

Aggregates are independent consistency boundaries. They should **never**
hold direct object references (`HasOne`, `HasMany`, `Reference`) to other
aggregates — doing so would create hidden transactional coupling.

Instead, reference another aggregate by storing its identity as a simple
`Identifier` or `String` field:

```python
@domain.aggregate
class Order:
    customer_id = Identifier(required=True)  # References Customer aggregate
    items = HasMany("OrderItem")

@domain.aggregate
class Customer:
    name: String(max_length=100)
    email = ValueObject("Email")
```

When you need to load the referenced aggregate, do so explicitly through
its repository:

```python
customer = domain.repository_for(Customer).get(order.customer_id)
```

This keeps each aggregate independently loadable, persistable, and
deployable. For keeping aggregates in sync after state changes, use
[domain events](../domain-behavior/raising-events.md).

## Cascade Behavior

When an aggregate is persisted, all enclosed entities (connected via
`HasOne`/`HasMany`) are persisted together as part of the same transaction.
When an aggregate is deleted, its enclosed entities are deleted with it —
they cannot exist independently.

Removing an entity from a `HasMany` collection (via `remove_<field>`) marks
it for deletion during the next persistence operation.

## Loading Behavior

Entity associations within an aggregate are loaded **eagerly**. When you
retrieve an aggregate from a repository, all its enclosed entities are
loaded in the same operation. There is no lazy loading — the entire
aggregate graph is materialized at once.

This is by design: an aggregate is a consistency boundary, and partial
loading would make it impossible to enforce invariants that span the root
and its children.

## Event Sourcing Considerations

For **event-sourced aggregates** (`is_event_sourced=True`), associations
behave differently because state is reconstructed from events rather than
loaded from a database:

- Entity collections (`HasMany`, `HasOne`) start empty after event replay
  begins and are populated only by `@apply` handlers that process the
  relevant events.
- There are no database-level foreign keys or joins — the aggregate's
  entire state (including its entities) is rebuilt from its event stream.
- Cross-aggregate references by identity work the same way as in standard
  aggregates.

---

!!! tip "See also"
    **Concept overview:** [Aggregates](../../concepts/building-blocks/aggregates.md) — How aggregates define consistency boundaries that contain entities and value objects.

    **Related guides:**

    - [Entities](./entities.md) — Define entities with identity within an aggregate.
    - [Value Objects](./value-objects.md) — Embed immutable descriptive objects in aggregates.

    **Reference:**

    - [Association Fields](../../reference/fields/association-fields.md) — Full API reference for `HasOne`, `HasMany`, `Reference`, and `ValueObject` fields.

    **Patterns:**

    - [Design Small Aggregates](../../patterns/design-small-aggregates.md) — Why smaller aggregates lead to better systems.
