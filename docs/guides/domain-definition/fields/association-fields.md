# Association Fields

!!! abstract "Applies to: DDD · CQRS · Event Sourcing"


Association fields in Protean are designed to represent and manage
relationships between different domain models. They facilitate the modeling of
complex relationships, while encapsulating the technical aspects of persisting
data.

Note that while Aggregates and Entities can manage associations, they can
never link to another Aggregate directly. Aggregates are transaction boundaries
and no transaction should span across aggregates. Read more in
[Aggregate concepts](../../../core-concepts/domain-elements/aggregates.md).

For a comprehensive guide on relationships, see [Expressing Relationships](../relationships.md).

## `HasOne`

Represents an one-to-one association between an aggregate and its entities.
This field is used to define a relationship where an aggregate is associated
with at most one instance of a child entity.

```python hl_lines="10 13"
{! docs_src/guides/domain-definition/fields/association-fields/001.py !}
```

!!!note
    If you carefully observe the `HasOne` field declaration, the child entity's
    name is a string value! This is usually the way to avoid circular references.
    It applies to all aspects of Protean that link two entities - the string
    value will be resolved to the class at runtime.

The `Author` entity can now be persisted along with the `Book` aggregate:

```shell hl_lines="3 12-13"
In [1]: book = Book(
   ...:     title="The Great Gatsby",
   ...:     author=Author(name="F. Scott Fitzgerald")
   ...: )

In [2]: domain.repository_for(Book).add(book)
Out[2]: <Book: Book object (id: a4a642d9-87ed-44de-9889-c687466f171b)>

In [3]: domain.repository_for(Book)._dao.query.all().items[0].to_dict()
Out[3]: 
{'title': 'The Great Gatsby',
 'author': {'name': 'F. Scott Fitzgerald',
  'id': '1f275e92-9872-4d96-b999-4ef0fbe61013'},
 'id': 'a4a642d9-87ed-44de-9889-c687466f171b'}
```

!!!note
    Protean adds a `Reference` field to child entities to preserve the inverse
    relationship - from child entity to aggregate - when persisted. This is
    visible if you introspect the fields of the Child Entity.

    ```shell hl_lines="7 13"
    In [1]: from protean.reflection import declared_fields, attributes

    In [2]: declared_fields(Author)
    Out[2]: 
    {'name': String(required=True, max_length=50),
    'id': Auto(identifier=True),
    'book': Reference()}
    
    In [3]: attributes(Author)
    Out[3]: 
    {'name': String(required=True, max_length=50),
    'id': Auto(identifier=True),
    'book_id': _ReferenceField()}
    ```

We will further review persistence related aspects around associations in the
Repository section.
<!-- FIXME Link Repository section -->

## `HasMany`

Represents a one-to-many association between two entities. This field is used
to define a relationship where an aggregate has multiple instances of a child
entity.

```python hl_lines="11"
{! docs_src/guides/domain-definition/fields/association-fields/002.py !}
```

Protean provides helper methods that begin with `add_` and `remove_` to add
and remove child entities from the `HasMany` relationship.

```shell hl_lines="4-5 12-13 16 23"
In [1]: post = Post(
   ...:     title="Foo",
   ...:     comments=[
   ...:         Comment(content="Bar"),
   ...:         Comment(content="Baz")
   ...:     ]
   ...: )

In [2]: post.to_dict()
Out[2]: 
{'title': 'Foo',
 'comments': [{'content': 'Bar', 'id': '085ed011-15b3-48e3-9363-99a53bc9362a'},
  {'content': 'Baz', 'id': '4790cf87-c234-42b6-bb03-1e0599bd6c0f'}],
 'id': '29943ac9-a9eb-497b-b6d2-466b30ecd5f5'}

In [3]: post.add_comments(Comment(content="Qux"))

In [4]: post.to_dict()
Out[4]: 
{'title': 'Foo',
 'comments': [{'content': 'Bar', 'id': '085ed011-15b3-48e3-9363-99a53bc9362a'},
  {'content': 'Baz', 'id': '4790cf87-c234-42b6-bb03-1e0599bd6c0f'},
  {'content': 'Qux', 'id': 'b1a7aeda-81ca-4d0b-9d7e-6fe0c000b8af'}],
 'id': '29943ac9-a9eb-497b-b6d2-466b30ecd5f5'}
```

You can also use helper methods that begin with `get_one_from_` and `filter_` to filter
for specific entities within the instances.

`get_one_from_` returns a single entity. It raises `ObjectNotFoundError` if no matching
entity for the criteria is found and `TooManyObjectsError` if more than
one entity is found.

`filter` returns a `list` of zero or more matching entities.

```shell hl_lines="9 12"
In [1]: post = Post(
   ...:     title="Foo",
   ...:     comments=[
   ...:         Comment(content="Bar", rating=2.5),
   ...:         Comment(content="Baz", rating=5)
   ...:     ]
   ...: )

In [2]: post.filter_comments(content="Bar", rating=2.5)
Out[2]: [<Comment: Comment object (id: 3b7fd92e-be11-4b3b-96e9-1caf02779f14)>]

In [3]: comments = post.filter_comments(content="Bar", rating=2.5)

In [4]: comments[0].to_dict()
Out[4]: {'content': 'Bar', 'rating': 2.5, 'id': '3b7fd92e-be11-4b3b-96e9-1caf02779f14'}
```

## `Reference`

A `Reference` field establishes the inverse relationship from child entities to their parent aggregate. While `HasOne` and `HasMany` define the forward relationship (parent to child), the `Reference` field enables navigation from child to parent.

Every entity associated with an aggregate automatically gets a `Reference` field created for it, unless explicitly defined. The field name is derived from the aggregate's name (e.g., `Post` becomes `post`).

```python hl_lines="4"
@domain.entity(part_of=Post)
class Comment:
    content = String(max_length=500)
    post = Reference(Post)  # Explicit reference field
```

### Shadow Fields

Reference fields automatically create shadow fields (foreign key attributes) that store the actual identifier values. These shadow fields follow the naming convention `<field_name>_<id_field>`:

```shell hl_lines="6"
In [1]: from protean.reflection import attributes
In [2]: attributes(Comment)
Out[2]: 
{'content': String(max_length=500),
 'id': Auto(identifier=True),
 'post': Reference(),
 'post_id': _ReferenceField()}
```

### Custom Shadow Field Names

Use `referenced_as` to specify a custom name for the shadow field:

```python
@domain.entity(part_of=Order)
class OrderItem:
    quantity = Integer()
    order = Reference(Order, referenced_as="order_number")
    # Creates shadow field 'order_number' instead of 'order_id'
```

The same name has to be specified on the `HasOne` or `HasMany` field with the `via` option, to establish the two-way relationship.

```python
@domain.aggregate
class Order:
   ordered_at = DateTime()
   items = HasMany(OrderItem, via="order_number")
```

## Customizing Foreign Keys with `via`

By default, association fields create foreign keys following the pattern `<aggregate_name>_id`. The `via` parameter allows you to specify a custom field name for the foreign key relationship:

```python hl_lines="4 9"
@domain.aggregate  
class Product:
    name = String(max_length=100)
    reviews = HasMany("Review", via="product_sku")

@domain.entity(part_of=Product)
class Review:
    content = String(max_length=1000)
    product_sku = String()  # Custom foreign key field
```

This is particularly useful when you want to link entities using fields other than the default identifier, or when you need specific naming conventions for your foreign key relationships.