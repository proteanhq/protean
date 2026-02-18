# Aggregates

!!! abstract "Applies to: DDD · CQRS · Event Sourcing"


DDD emphasizes on representing domain concepts as closely as possible in code.
To accomplish this, DDD outlines a set of tactical patterns that we could use
to model the domain. When you want to model domain concepts that have a unique
identity and that change continuously over a long period of time, you
represent them as [Aggregates](#aggregates) and [Entities](./entities.md).

Aggregates are fundamental, coarse-grained building blocks of a domain model.
They are conceptual wholes - they enclose all behaviors and data of a distinct
domain concept. Aggregates are often composed of one or more Aggregate
Elements, that work together to codify the concept.

Traditional DDD refers to such entities as **Aggregate Roots** because they
compose and manage a cluster of objects. In Protean, the term ***Aggregate***
and ***Aggregate Root*** are synonymous.

Aggregates are defined with the `Domain.aggregate` decorator:

```python hl_lines="8"
{! docs_src/guides/domain-definition/001.py !}
```

In the example above, `Post` is defined to as an Aggregate with two fields,
`name` and `created_on`, and registered with the `publishing` domain.

Read more about
[`Domain.aggregate`](../compose-a-domain/element-decorators.md#domainaggregate)
in [element decorators](../compose-a-domain/element-decorators.md).

## Fields

Aggregates enclose a number of fields and associate behaviors with them to
represent a domain concept.

```python hl_lines="10-11"
{! docs_src/guides/domain-definition/001.py !}
```

Here, `Post` aggregate has two fields:

- `name`, a `String` field
- `created_on`, a `Date` field

You can finely configure each field with various options (like `max_length` in
`String`'s case), add validations (like `required` to indicate that a field is
mandatory), and also fine-tune how it is persisted (like a database column
name in `referenced_as`).

The full list of available fields in Protean and their options is available in
[Data Fields](../domain-definition/fields/index.md) section.

## Initialization

An aggregate can be initialized by passing field values as key-value pairs:

```python hl_lines="17"
{! docs_src/guides/domain-definition/002.py !}
```

This would output something like:

```json
{
    "name": "My First Post",
    "created_on": "2024-01-01",
    "id": "d42d695a-0b9b-4c4f-b8c0-c122f67e4e58"
}
```

You see an `id` attribute appear in the results. We discuss **identity**
deeply in the [identity](../essentials/identity.md) section.

### Event-Sourced Aggregates

For **event-sourced aggregates**, the standard constructor is typically not
used in business methods. Instead, factory methods use `_create_new()` to
create a blank aggregate with auto-generated identity, then raise a
creation event whose `@apply` handler populates the remaining state:

```python
@domain.aggregate(is_event_sourced=True)
class Order:
    customer_name: String(max_length=150, required=True)
    status: String(max_length=20, default="PENDING")

    @classmethod
    def place(cls, customer_name):
        order = cls._create_new()
        order.raise_(OrderPlaced(
            order_id=str(order.id),
            customer_name=customer_name,
        ))
        return order

    @apply
    def when_placed(self, event: OrderPlaced):
        self.customer_name = event.customer_name
        self.status = "PENDING"
```

This ensures the creation event's `@apply` handler is the single source
of truth for setting initial state — the same handler runs during both
live creation and event replay. See the
[Event Sourcing tutorial](../getting-started/tutorial/14-event-sourcing.md)
for a complete walkthrough.

## Inheritance

Often, you may want to have common attributes across aggregates in your domain.
`created_at` and `updated_at` are great examples. You can declare these common
attributes in a base aggregate and inherit it in concrete classes:

```python hl_lines="9-10 16"
{! docs_src/guides/domain-definition/003.py !}
```

Notice that the `TimeStamped` class has been marked `abstract=True`. This is
optional, but considered good practice, because in this example, `TimeStamped`
will not be instantiated by itself. It's explicit purpose is to serve as a base
class for other aggregates.

!!!note
    You will see further on that it is possible to generate database schema
    definitions automatically from `Aggregate` and `Entity` elements. Marking
    a class as `abstract` also has the benefit that database schema definitions
    will be generated accidentally.

The `User` aggregate will inherit the two fields from the parent `TimeStamped`
class:

```shell hl_lines="3 4"
>>> from protean.utils.reflection import declared_fields
>>> declared_fields(User)
{'created_at': DateTime(default=utc_now),
 'updated_at': DateTime(default=utc_now),
 'id': Auto(),
 'name': String(max_length=30),
 'timezone': String(max_length=30)}
```

## Configuration

An aggregate's behavior can be customized with by passing additional options
to its decorator, or with a `Meta` class as we saw earlier.

### `abstract`

Marks an Aggregate as abstract if `True`. If abstract, the aggregate
cannot be instantiated and needs to be subclassed.

```python hl_lines="12"
{! docs_src/guides/domain-definition/003.py !}
```

Trying to instantiate an abstact Aggregate will throw `NotSupportedError`:

```shell
>>> t = TimeStamped()
NotSupportedError                         Traceback (most recent call last)
...
NotSupportedError: TimeStamped class has been marked abstract and cannot be instantiated
```

### `auto_add_id_field`

If `True`, the aggregate will not contain an identifier field (acting as
primary key) added by default. This option is usually combined with
`abstract` to create classes that are meant to be subclassed by other
aggregates.

### `provider`

Specifies the database that the aggregate is persisted in.

Aggregates are connected to underlying data stores via providers. The
definitions of these providers are supplied within the `databases` key in the
Domain’s configuration. Protean identifies the correct data store, establishes
the connection and takes responsibility of persisting the data.

```python hl_lines="5-16 19"
{! docs_src/guides/domain-definition/004.py !}
```

Protean requires at least one provider, named `default`, to be specified in the
configuration. When no provider is explicitly specified, Aggregate objects are
persisted into the default data store. Refer to `Configuration Management`
for more details.
<!-- FIXME Update Configuration Management link in above paragraph -->

### `schema_name`

The name to store and retrieve the aggregate from the persistence store. By
default, `schema_name` is the snake case version of the Aggregate's name.

```python hl_lines="12-13"
{! docs_src/guides/domain-definition/006.py !}
```

### `model`

Protean automatically constructs a representation of the aggregate that is
compatible with the configured database. While the generated model suits most
use cases, you can also explicitly construct a model and associate it with
the aggregate.

```python hl_lines="22-25"
{! docs_src/guides/domain-definition/005.py !}
```

!!!note
    Custom models are associated with a specific database type and are
    used only when the configured database is active. Refer to the section on
    `Customizing Persistence schemas` for more information.
    <!-- FIXME Add link to customizing persistence schemas -->

### `stream_category`

The [stream category](../essentials/stream-categories.md) defines the logical grouping for all messages (events and commands) related to an aggregate. It serves as the foundation for message routing, subscription management, and event sourcing in Protean.

By default, the stream category is automatically derived as the snake_case version of the aggregate's class name:

```python
@domain.aggregate
class User:
    ...
# Stream category: "user"

@domain.aggregate
class OrderItem:
    ...
# Stream category: "order_item"
```

You can explicitly specify a stream category:

```python
@domain.aggregate(stream_category="customer_orders")
class Order:
    ...
# Stream category: "customer_orders"
```

The stream category is used by:

- **Handlers** to determine which message streams to subscribe to
- **Event Store** to organize events for event sourcing
- **Subscriptions** to poll for new messages
- **Brokers** to route messages to the correct destinations

For a comprehensive understanding of stream categories, including message organization, handler subscriptions, cross-aggregate patterns, and best practices, see the [Stream Categories](../essentials/stream-categories.md) guide.

## Associations

Protean provides multiple options for Aggregates to weave object graphs with enclosed Entities. Associations define relationships between the aggregate and its child entities, establishing clear parent-child hierarchies within aggregate boundaries.

For comprehensive documentation on relationships, see [Expressing Relationships](./relationships.md).

### `HasOne`

A HasOne field establishes a has-one relation with the entity. In the example
below, `Post` has exactly one `Statistic` record associated with it.

```python hl_lines="18 22-26"
{! docs_src/guides/domain-definition/008.py !}
```

```shell
In [1]: post = Post(title='Foo')

In [2]: post.stats = Statistic(likes=10, dislikes=1)

In [3]: current_domain.repository_for(Post).add(post)
```

### `HasMany`

```python hl_lines="19 29-33"
{! docs_src/guides/domain-definition/008.py !}
```

Below is an example of adding multiple comments to the domain defined above:

```shell
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

### Bidirectional Relationships

Associations automatically create bidirectional relationships. Child entities get `Reference` fields that point back to their parent aggregate, enabling navigation in both directions:

```shell
# Navigation from parent to child
In [8]: post = current_domain.repository_for(Post).get(post.id)
In [9]: post.comments
Out[9]: [<Comment: Comment object (...)>, <Comment: Comment object (...)>]

# Navigation from child to parent
In [10]: comment = post.comments[0]
In [11]: comment.post
Out[11]: <Post: Post object (id: e288ee30-e1d5-4fb3-94d8-d8083a6dc9db)>

# Access to foreign key value
In [12]: comment.post_id
Out[12]: 'e288ee30-e1d5-4fb3-94d8-d8083a6dc9db'
```

The `Reference` field (`comment.post`) provides access to the full parent object, while the shadow field (`comment.post_id`) contains the foreign key value.
