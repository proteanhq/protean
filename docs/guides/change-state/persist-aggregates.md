# Persist Aggregates

!!! abstract "Applies to: DDD · CQRS · Event Sourcing"


Aggregates are saved into the configured database using `add` method of the
repository.

```python hl_lines="20"
{! docs_src/guides/change_state_001.py !}
```

1.  Identity, by default, is a string.

```shell
In [1]: domain.repository_for(Person).get("1")
Out[1]: <Person: Person object (id: 1)>

In [2]: domain.repository_for(Person).get("1").to_dict()
Out[2]: {'name': 'John Doe', 'email': 'john.doe@localhost', 'id': '1'}
```

## Transaction

The `add` method is enclosed in a [Unit of Work](unit-of-work.md) context by
default. Changes are committed to the persistence store when the Unit Of Work
context exits.

The following calls are equivalent in behavior:

```python
...
# Version 1
domain.repository_for(Person).add(person)
...

...
# Version 2
from protean import UnitOfWork

with UnitOfWork():
    domain.repository_for(Person).add(person)    
...
```

This means changes across the aggregate cluster are committed as a single
transaction (assuming the underlying database supports transactions, of course).

```python hl_lines="22-30 33"
{! docs_src/guides/change_state_002.py !}
```

!!!note
    This is especially handy in ***Relational databases*** because each entity is a
    separate table.

## Events

The `add` method also publishes events to configured brokers upon successfully
persisting to the database.

```python hl_lines="15"
{! docs_src/guides/change_state_003.py !}
```

```shell hl_lines="12-16 21-22"
In [1]: post = Post(title="Events in Aggregates", body="Lorem ipsum dolor sit amet, consectetur adipiscing...")

In [2]: post.to_dict()
Out[2]: 
{'title': 'Events in Aggregates',
 'body': 'Lorem ipsum dolor sit amet, consectetur adipiscing...',
 'published': False,
 'id': 'a9ea7763-c5b2-4c8c-9c97-43ba890517d0'}

In [3]: post.publish()

In [4]: post._events
Out[4]: [<PostPublished: PostPublished object ({
    'post_id': 'a9ea7763-c5b2-4c8c-9c97-43ba890517d0',
    'body': 'Lorem ipsum dolor sit amet, consectetur adipiscing...'
})>]

In [5]: domain.repository_for(Post).add(post)
Out[5]: <Post: Post object (id: a9ea7763-c5b2-4c8c-9c97-43ba890517d0)>

In [6]: post._events
Out[6]: []
```

## Updates

Recall that Protean repositories behave like a `set` collection. Updating is
as simple as mutating an aggregate and persisting it with `add` again.

```shell hl_lines="15 20 22 25 27"
In [1]: post = Post(
   ...:     id="1",
   ...:     title="Events in Aggregates",
   ...:     body="Lorem ipsum dolor sit amet, consectetur adipiscing..."
   ...: )

In [2]: domain.repository_for(Post).add(post)
Out[2]: <Post: Post object (id: 1)>

In [3]: domain.repository_for(Post).get("1")
Out[3]: <Post: Post object (id: 1)>

In [4]: domain.repository_for(Post).get("1").to_dict()
Out[4]: 
{'title': 'Events in Aggregates',
 'body': 'Lorem ipsum dolor sit amet, consectetur adipiscing...',
 'published': False,
 'id': '1'}

In [5]: post.title = "(Updated Title) Events in Entities"

In [6]: domain.repository_for(Post).add(post)
Out[6]: <Post: Post object (id: 1)>

In [7]: domain.repository_for(Post).get("1").to_dict()
Out[7]: 
{'title': '(Updated Title) Events in Entities',
 'body': 'Lorem ipsum dolor sit amet, consectetur adipiscing...',
 'published': False,
 'id': '1'}
```