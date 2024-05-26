# Aggregates

DDD emphasizes on representing domain concepts as closely as possible in code.
To accomplish this, DDD outlines a set of tactical patterns that we could use
to model the domain. When you want to model domain concepts that have a unique
identity and that change continuously over a long period of time, you
represent them as [Aggregates](#aggregates) and [Entities](#entities).

Aggregates are fundamental, coarse-grained building blocks of a domain model.
They are conceptual wholes - they enclose all behaviors and data of a distinct
domain concept. Aggregates are often composed of one or more Aggregate
Elements, that work together to codify the concept.

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
[Data Fields](../data-fields/index.md) section.

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
deeply in a [later](identity.md) section.

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
>>> from protean.reflection import declared_fields
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

Available options are:

### `abstract`

When specified marks an Aggregate as abstract. If abstract, the aggregate
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
