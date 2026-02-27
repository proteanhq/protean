# Aggregates

<span class="pathway-tag pathway-tag-ddd">DDD</span> <span class="pathway-tag pathway-tag-cqrs">CQRS</span> <span class="pathway-tag pathway-tag-es">ES</span>

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
--8<-- "guides/domain-definition/001.py:full"
```

In the example above, `Post` is defined to as an Aggregate with two fields,
`name` and `created_on`, and registered with the `publishing` domain.

Read more about
[`Domain.aggregate`](../../reference/domain-elements/element-decorators.md#domainaggregate)
in [element decorators](../../reference/domain-elements/element-decorators.md).

## Fields

Aggregates enclose a number of fields and associate behaviors with them to
represent a domain concept.

```python hl_lines="9-10"
--8<-- "guides/domain-definition/001.py:full"
```

Here, `Post` aggregate has two fields:

- `name`, a `String` field
- `created_on`, a `Date` field

You can finely configure each field with various options (like `max_length` in
`String`'s case), add validations (like `required` to indicate that a field is
mandatory), and also fine-tune how it is persisted (like a database column
name in `referenced_as`).

The full list of available fields in Protean and their options is available in
[Data Fields](../../reference/fields/index.md) section.

## Initialization

An aggregate can be initialized by passing field values as key-value pairs:

```python hl_lines="17"
--8<-- "guides/domain-definition/002.py:full"
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
deeply in the [identity](../../reference/domain-elements/identity.md) section.

---

!!! note "Advanced"
    The following section covers event-sourced aggregate initialization,
    relevant when using the [Event Sourcing](../pathways/event-sourcing.md) pathway.

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
[Event Sourcing pathway](../pathways/event-sourcing.md)
for a complete walkthrough.

## Inheritance

Often, you may want to have common attributes across aggregates in your domain.
`created_at` and `updated_at` are great examples. You can declare these common
attributes in a base aggregate and inherit it in concrete classes:

```python hl_lines="9-10 16"
--8<-- "guides/domain-definition/003.py:full"
```

Notice that the `TimeStamped` class has been marked `abstract=True`. This is
optional, but considered good practice, because in this example, `TimeStamped`
will not be instantiated by itself. It's explicit purpose is to serve as a base
class for other aggregates.

!!!note
    You will see further on that it is possible to generate database schema
    definitions automatically from `Aggregate` and `Entity` elements. Marking
    a class as `abstract` also has the benefit that database schema definitions
    will not be generated accidentally.

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

---


## Configuration

An aggregate's behavior can be customized by passing options to its decorator.
Here are the most commonly used options — see
[element decorators](../../reference/domain-elements/element-decorators.md)
for the complete reference.

### `abstract`

Marks an Aggregate as abstract if `True`. If abstract, the aggregate
cannot be instantiated and needs to be subclassed.

```python hl_lines="12"
--8<-- "guides/domain-definition/003.py:full"
```

### `provider`

Specifies the database that the aggregate is persisted in:

```python hl_lines="5-16 19"
--8<-- "guides/domain-definition/004.py:full"
```

Protean requires at least one provider, named `default`, to be specified in the
configuration. When no provider is explicitly specified, Aggregate objects are
persisted into the default data store.
Refer to [Configuration](../../reference/configuration/index.md) for more details.

### `stream_category`

The [stream category](../../concepts/async-processing/stream-categories.md)
defines the logical grouping for all messages related to an aggregate:

```python
@domain.aggregate(stream_category="customer_orders")
class Order:
    ...
# Stream category: "customer_orders"
```

By default, it is the snake_case version of the class name.

### `fact_events`

When set to `True`, Protean automatically generates a fact event
(containing the aggregate's full state) every time the aggregate is
persisted. Fact events are written to a separate stream
(`<stream_category>-fact-<aggregate_id>`) and are useful for cross-context
integration where consumers need the complete state rather than individual
deltas.

```python
@domain.aggregate(fact_events=True)
class Customer:
    name: String(max_length=100)
    email: String(max_length=255)
```

See [Fact Events](../domain-behavior/raising-events.md#fact-events) and
the [Fact Events as Integration Contracts](../../patterns/fact-events-as-integration-contracts.md)
pattern for details.

### `limit`

The maximum number of records returned by default queries (default: `100`).
Set to `None` or a negative value to remove the limit:

```python
@domain.aggregate(limit=500)
class Product:
    ...

@domain.aggregate(limit=None)  # No limit
class AuditLog:
    ...
```

### `aggregate_cluster`

Groups an aggregate with other aggregates into a named cluster. This is
primarily used internally by Protean to organize aggregate-related elements
and resolve cross-references.

### `is_event_sourced`

When `True`, the aggregate's state is derived entirely from its event
stream rather than loaded from a database. Business methods must use
`raise_()` and `@apply` handlers instead of direct mutation. See the
[Event Sourcing pathway](../pathways/event-sourcing.md) for a complete
walkthrough.

For details on `auto_add_id_field`, `schema_name`, `database_model`, and
other options, see
[element decorators](../../reference/domain-elements/element-decorators.md).

## The `defaults()` Hook

Override the `defaults()` method when an attribute's default depends on
other attribute values:

```python
@domain.aggregate
class Invoice:
    subtotal: Float(required=True)
    tax_rate: Float(default=0.1)
    total: Float()

    def defaults(self):
        if self.total is None:
            self.total = self.subtotal * (1 + self.tax_rate)
```

`defaults()` runs during initialization, after all field values have been
set but before invariants are checked. Aggregates, entities, and value
objects all support this hook.

## Associations

Protean provides multiple options for Aggregates to weave object graphs with enclosed Entities. Associations define relationships between the aggregate and its child entities, establishing clear parent-child hierarchies within aggregate boundaries.

For comprehensive documentation on relationships, see [Expressing Relationships](./relationships.md).

### `HasOne`

A HasOne field establishes a has-one relation with the entity. In the example
below, `Post` has exactly one `Statistic` record associated with it.

```python hl_lines="18 22-26"
--8<-- "guides/domain-definition/008.py:full"
```

```shell
In [1]: post = Post(title='Foo')

In [2]: post.stats = Statistic(likes=10, dislikes=1)

In [3]: current_domain.repository_for(Post).add(post)
```

### `HasMany`

```python hl_lines="19 29-33"
--8<-- "guides/domain-definition/008.py:full"
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

## Common Errors

| Exception | When it occurs |
|---|---|
| `ValidationError` | Field validation fails during construction or mutation (e.g. missing `required` field, value exceeds `max_length`). Contains a `messages` dict mapping field names to error lists. |
| `ValidationError` | An `@invariant.post` or `@invariant.pre` check raises a validation error. |
| `IncorrectUsageError` | Trying to instantiate an abstract aggregate directly. |
| `IncorrectUsageError` | Raising an event that is not associated with this aggregate (`part_of` mismatch). |
| `NotImplementedError` | Event-sourced aggregate raises an event with no matching `@apply` handler. |

---

!!! tip "See also"
    **Concept overview:** [Aggregates](../../concepts/building-blocks/aggregates.md) — What aggregates are, their core properties, and why they matter.

    **Decision guidance:** [Choosing Element Types](../../concepts/building-blocks/choosing-element-types.md) — When to use an aggregate vs. an entity vs. a value object.

    **Related guides:**

    - [Expressing Relationships](./relationships.md) — Full relationship and association documentation.
    - [Invariants](../domain-behavior/invariants.md) — Enforcing business rules and state guards.
    - [Raising Events](../domain-behavior/raising-events.md) — Publishing domain events from aggregates.
    - [Repositories](../change-state/repositories.md) — Persisting and retrieving aggregates.

    **Patterns:**

    - [Design Small Aggregates](../../patterns/design-small-aggregates.md) — Why smaller aggregates lead to better systems.
    - [Encapsulate State Changes](../../patterns/encapsulate-state-changes.md) — Protecting aggregate internals with controlled mutation.
    - [Factory Methods for Aggregate Creation](../../patterns/factory-methods-for-aggregate-creation.md) — Encapsulating complex construction logic.
    - [Model Aggregate Lifecycle as a State Machine](../../patterns/aggregate-state-machines.md) — Explicit states and guarded transitions.
    - [One Aggregate Per Transaction](../../patterns/one-aggregate-per-transaction.md) — Keeping transaction boundaries clean.
