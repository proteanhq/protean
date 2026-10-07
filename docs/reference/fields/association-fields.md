# Association Fields

!!! abstract "Applies to: DDD · CQRS · Event Sourcing"


Association fields in Protean are designed to represent and manage
relationships between different domain models. They facilitate the modeling of
complex relationships, while encapsulating the technical aspects of persisting
data.

Note that while Aggregates and Entities can manage associations, they can
never link to another Aggregate directly. Aggregates are transaction boundaries
and no transaction should span across aggregates. Read more in
[Aggregate concepts](../../concepts/building-blocks/aggregates.md).

For a comprehensive guide on relationships, see [Expressing Relationships](../../guides/domain-definition/relationships.md).

## `HasOne`

Represents an one-to-one association between an aggregate and its entities.
This field is used to define a relationship where an aggregate is associated
with at most one instance of a child entity.

```python hl_lines="10 13"
--8<-- "guides/domain-definition/fields/association-fields/001.py:full"
```

!!!note
    If you carefully observe the `HasOne` field declaration, the child entity's
    name is a string value. This is the usual way to avoid circular references.
    It applies to all aspects of Protean that link two entities - the string
    value will be resolved to the class at runtime.

The `Author` entity can now be persisted along with the `Book` aggregate:

```shell hl_lines="3 13-14"
In [1]: book = Book(
   ...:     title="The Great Gatsby",
   ...:     author=Author(name="F. Scott Fitzgerald")
   ...: )

In [2]: domain.repository_for(Book).add(book)
Out[2]: <Book: Book object (id: a4a642d9-87ed-44de-9889-c687466f171b)>

In [3]: domain.repository_for(Book).query.all().items[0].to_dict()
Out[3]:
{'title': 'The Great Gatsby',
 'id': 'a4a642d9-87ed-44de-9889-c687466f171b',
 'author': {'name': 'F. Scott Fitzgerald',
  'id': '1f275e92-9872-4d96-b999-4ef0fbe61013'},
 '_version': 0}
```

!!!note
    Protean adds a `Reference` field to child entities to preserve the inverse
    relationship - from child entity to aggregate - when persisted. This is
    visible if you introspect the fields of the Child Entity.

    ```shell hl_lines="4 7"
    In [1]: from protean.utils.reflection import declared_fields, attributes

    In [2]: list(declared_fields(Author))
    Out[2]: ['name', 'id', 'book']

    In [3]: list(attributes(Author))
    Out[3]: ['name', 'id', 'book_id']
    ```

We will further review persistence related aspects around associations in the
Repository section.
<!-- FIXME Link Repository section -->

## `HasMany`

Represents a one-to-many association between two entities. This field is used
to define a relationship where an aggregate has multiple instances of a child
entity.

```python hl_lines="11"
--8<-- "guides/domain-definition/fields/association-fields/002.py:full"
```

Protean provides helper methods that begin with `add_` and `remove_` to add
and remove child entities from the `HasMany` relationship.

```shell hl_lines="4-5 14-15 18 27"
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
 'body': None,
 'id': '29943ac9-a9eb-497b-b6d2-466b30ecd5f5',
 'comments': [{'content': 'Bar', 'rating': None, 'id': '085ed011-15b3-48e3-9363-99a53bc9362a'},
  {'content': 'Baz', 'rating': None, 'id': '4790cf87-c234-42b6-bb03-1e0599bd6c0f'}],
 '_version': -1}

In [3]: post.add_comments(Comment(content="Qux"))

In [4]: post.to_dict()
Out[4]:
{'title': 'Foo',
 'body': None,
 'id': '29943ac9-a9eb-497b-b6d2-466b30ecd5f5',
 'comments': [{'content': 'Bar', 'rating': None, 'id': '085ed011-15b3-48e3-9363-99a53bc9362a'},
  {'content': 'Baz', 'rating': None, 'id': '4790cf87-c234-42b6-bb03-1e0599bd6c0f'},
  {'content': 'Qux', 'rating': None, 'id': 'b1a7aeda-81ca-4d0b-9d7e-6fe0c000b8af'}],
 '_version': -1}
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

```python hl_lines="10"
--8<-- "guides/domain-definition/fields/association-fields/003.py:explicit_reference"
```

### Shadow Fields

Reference fields automatically create shadow fields (foreign key attributes) that store the actual identifier values. These shadow fields follow the naming convention `<field_name>_<id_field>`:

```shell hl_lines="4"
In [1]: from protean.utils.reflection import attributes

In [2]: list(attributes(Comment))
Out[2]: ['content', 'id', 'post_id']
```

### Custom Shadow Field Names

Use `referenced_as` to specify a custom name for the shadow field:

```python
--8<-- "guides/domain-definition/fields/association-fields/004.py:order_item"
```

The same name has to be specified on the `HasOne` or `HasMany` field with the `via` option, to establish the two-way relationship.

```python
--8<-- "guides/domain-definition/fields/association-fields/004.py:order"
```

## Customizing Foreign Keys with `via`

By default, association fields name the foreign key `<aggregate_name>_<identifier_name>`, such as `product_id` for a `Product` whose identifier is `id`. The `via` parameter allows you to specify a custom field name for the foreign key relationship:

```python hl_lines="4 10"
--8<-- "guides/domain-definition/fields/association-fields/005.py:via"
```

Use it when the foreign key has to match a column name in an existing schema. The value stored in the `via` field is still the parent's identifier, and Protean still adds the default `<aggregate_name>_<identifier_name>` field (`product_id` here) next to it.
