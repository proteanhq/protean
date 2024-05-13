# Association Fields

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
