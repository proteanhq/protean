# Expressing Relationships

!!! abstract "Applies to: DDD · CQRS · Event Sourcing"


Protean provides a comprehensive relationship system that allows you to model complex associations between domain entities while maintaining clean separation of concerns. Relationships in Protean are expressed through association fields (`HasOne`, `HasMany`) and their corresponding reference fields (`Reference`), which work together to establish bidirectional linkages.

## Relationship Types

### One-to-One (HasOne)

A `HasOne` relationship represents a one-to-one association between an aggregate and a child entity. The aggregate can have at most one instance of the related entity.

```python
@domain.aggregate
class Blog:
    title = String(max_length=100)
    settings = HasOne("BlogSettings")

@domain.entity(part_of=Blog)
class BlogSettings:
    theme = String(max_length=50)
    allow_comments = Boolean(default=True)
```

### One-to-Many (HasMany)

A `HasMany` relationship represents a one-to-many association where an aggregate can contain multiple instances of a child entity.

```python
@domain.aggregate
class Post:
    title = String(max_length=100)
    comments = HasMany("Comment")

@domain.entity(part_of=Post)
class Comment:
    content = String(max_length=500)
    author = String(max_length=50)
```

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
    content = String(max_length=500)
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
    name = String(max_length=100)
    sku = String(identifier=True, max_length=20)
    reviews = HasMany("Review", via="product_sku")

@domain.entity(part_of=Product)
class Review:
    content = String(max_length=1000)
    rating = Integer(min_value=1, max_value=5)
    product_sku = String()  # Custom foreign key field
```

Without `via`, the foreign key would be `product_id`. With `via="product_sku"`, it uses `product_sku` instead.

### The `referenced_as` Parameter

The `referenced_as` parameter in Reference fields allows you to specify a custom name for the shadow field:

```python
@domain.entity(part_of=Order)
class OrderItem:
    product_name = String(max_length=100)
    order = Reference(Order, referenced_as="order_number")
    # Creates shadow field named 'order_number' instead of 'order_id'
```

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

## Working with Associations

### Adding Related Objects

Use helper methods to manage associations:

```python
post = Post(title="New Post")

# Add single comment
comment = Comment(content="First comment")
post.add_comments(comment)

# Add multiple comments
comments = [
    Comment(content="Second comment"),
    Comment(content="Third comment")
]
post.add_comments(comments)
```

### Querying Related Objects

Protean provides filtering capabilities for HasMany relationships:

```python
# Get all comments by a specific author
author_comments = post.filter_comments(author="john_doe")

# Get a single comment (raises error if not found or multiple found)
specific_comment = post.get_one_from_comments(author="jane_doe")
```

### Removing Related Objects

```python
# Remove specific comments
post.remove_comments(comment)

# Remove multiple comments
post.remove_comments([comment1, comment2])
```

## Transaction Boundaries

Relationships in Protean respect aggregate boundaries - associations only exist within an aggregate cluster. Aggregates cannot directly reference other aggregates, maintaining clear transaction boundaries and ensuring data consistency.

The relationship system ensures that all related entities within an aggregate are persisted and retrieved together, maintaining the aggregate's transactional integrity.