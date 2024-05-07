# Entities

Aggregates cluster multiple domain elements together to represent a concept.
They are usually composed of two kinds of elements - those with unique
identities (**Entities**) and those without (**Value Objects**).

Entities represent unique objects in the domain model just like Aggregates, but
they don’t manage other objects. Just like Aggregates, Entities are identified
by unique identities that remain the same throughout its life - they are not
defined by their attributes or values. For example, a passenger in the airline
domain is an Entity. The passenger’s identity remains the same across multiple
seat bookings, even if her profile information (name, address, etc.) changes
over time.

!!!note
    In Protean, Aggregates are actually entities that have taken on the
    additional responsibility of managing the lifecycle of one or more
    related entities.

# Definition

An Entity is defined with the `Domain.entity` decorator:

```python hl_lines="13-15"
{! docs_src/guides/domain-definition/007.py !}
```

An Entity has to be associated with an Aggregate. If `aggregate_cls` is not
specified while defining the identity, you will see an `IncorrectUsageError`:

```shell
>>> @publishing.entity
... class Comment:
...     content = String(max_length=500)
... 
IncorrectUsageError: {'_entity': ['Entity `Comment` needs to be associated with an Aggregate']}
```

An Entity cannot enclose another Entity (or Aggregate). Trying to do so will
throw `IncorrectUsageError`.

```shell
>>> @publishing.entity
... class SubComment:
...     parent = Comment()
... 
IncorrectUsageError: {'_entity': ['Entity `Comment` needs to be associated with an Aggregate']}
```
<!-- FIXME Ensure entities cannot enclose other entities. When entities
enclose something other than permitted fields, through an error-->

## Associations

Protean provides multiple options for Aggregates to weave object graphs with
enclosed Entities.

### `HasOne`

A HasOne field establishes a has-one relation with the entity. In the example
below, `Post` has exactly one `Statistic` record associated with it.

```python hl_lines="18 22-26"
{! docs_src/guides/domain-definition/008.py !}
```

```shell
>>> post = Post(title='Foo')
>>> post.stats = Statistic(likes=10, dislikes=1)
>>> current_domain.repository_for(Post).add(post)
```

### `HasMany`

```python hl_lines="19 29-33"
{! docs_src/guides/domain-definition/008.py !}
```

Below is an example of adding multiple comments to the domain defined above:

```shell
❯ protean shell --domain docs_src/guides/domain-definition/008.py
...
In [1]: from protean.globals import current_domain

In [2]: post = Post(title='Foo')

In [3]: comment1 = Comment(content='bar')

In [4]: comment2 = Comment(content='baz')

In [5]: post.add_comments([comment1, comment2])

In [6]: current_domain.repository_for(Post).add(post)
Out[6]: <Post: Post object (id: 19031285-6e27-4b7e-8b06-47ba6766208a)>

In [7]: post.to_dict()
Out[7]: 
{'title': 'Foo',
 'created_on': '2024-05-06 14:29:22.946329+00:00',
 'comments': [{'content': 'bar', 'id': 'af238f7b-5225-41fc-ae37-36cd4cface66'},
  {'content': 'baz', 'id': '5b7fa5ad-7b64-4194-ade7-fb7a4b3a8a15'}],
 'id': '19031285-6e27-4b7e-8b06-47ba6766208a'}
```

### `Reference`

A `Reference` field establishes the opposite relationship with the parent at
the data level. Entities that are connected by `HasMany` and `HasOne`
relationships can reference their owning object.

```shell
In [8]: post = current_domain.repository_for(Post).get(post.id)

In [9]: post.comments[0].post
Out[9]: <Post: Post object (id: e288ee30-e1d5-4fb3-94d8-d8083a6dc9db)>

In [10]: post.comments[0].post_id
Out[10]: 'e288ee30-e1d5-4fb3-94d8-d8083a6dc9db'
```
<!-- FIXME Add details about the attribute `<>_id` and the entity `<>` -->
