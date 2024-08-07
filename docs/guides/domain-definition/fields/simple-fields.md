# Simple Fields

## String

A string field, for small- to large-sized strings. For large amounts of text,
use [Text](#text).

```python hl_lines="9"
{! docs_src/guides/domain-definition/fields/simple-fields/001.py !}
```

**Optional Arguments**

- **`max_length`**: The maximum length (in characters) of the field.
Defaults to 255.
- **`min_length`**: The minimum length (in characters) of the field.
Defaults to 255.
- **`sanitize`**: Optionally turn off HTML sanitization. Default is `True`.

## Text

A large text field, to hold large amounts of text. Text fields do not have
size constraints.

```python hl_lines="10"
{! docs_src/guides/domain-definition/fields/simple-fields/002.py !}
```

**Optional Arguments**

- **`sanitize`**: Optionally turn off HTML sanitization. Default is `True`.

## Integer

An integer.

```python hl_lines="10"
{! docs_src/guides/domain-definition/fields/simple-fields/003.py !}
```

**Optional Arguments**

- **`max_value`**: The maximum numeric value of the field.
- **`min_value`**: The minimum numeric value of the field.

## Float

A floating-point number represented in Python by a float instance.

```python hl_lines="10"
{! docs_src/guides/domain-definition/fields/simple-fields/004.py !}
```

**Optional Arguments**

- **`max_value`**: The maximum numeric value of the field.
- **`min_value`**: The minimum numeric value of the field.

## Date

A date, represented in Python by a `datetime.date` instance.

```python hl_lines="12"
{! docs_src/guides/domain-definition/fields/simple-fields/005.py !}
```

```shell hl_lines="6"
In [1]: p = Post(title="It")

In [2]: p.to_dict()
Out[2]: 
{'title': 'It',
 'published_on': '2024-05-09',
 'id': '88a21815-7d9b-4138-9cac-5a06889d4318'}
```

Protean will intelligently convert a valid date string into a date object, with
the help of the venerable
[`dateutil`](https://dateutil.readthedocs.io/en/stable/) module.

```shell
In [1]: post = Post(title='Foo', published_on="2020-01-01")

In [2]: post.to_dict()
Out[2]: 
{'title': 'Foo',
 'published_on': '2020-01-01',
 'id': 'ffcb3b26-71f0-45d0-8ca0-b71a9603f792'}

In [3]: Post(title='Foo', published_on="2019-02-29")
ERROR: Error during initialization: {'published_on': ['"2019-02-29" has an invalid date format.']}
...
ValidationError: {'published_on': ['"2019-02-29" has an invalid date format.']}
```


## DateTime

A date and time, represented in Python by a `datetime.datetime` instance.

```python hl_lines="12"
{! docs_src/guides/domain-definition/fields/simple-fields/006.py !}
```

```shell
In [1]: p = Post(title="It")

In [2]: p.to_dict()
Out[2]: 
{'title': 'It',
 'created_at': '2024-05-09 17:12:11.373300+00:00',
 'id': '3a96e434-06ab-4244-80a8-76edbd621a27'}
```

## Boolean

A `True`/`False` field.

```python hl_lines="10"
{! docs_src/guides/domain-definition/fields/simple-fields/007.py !}
```

```shell hl_lines="6"
In [1]: u = User(name="John Doe")

In [2]: u.to_dict()
Out[2]: 
{'name': 'John Doe',
 'subscribed': False,
 'id': '69190dd4-12a6-4666-a799-9409ddab39cd'}
```

## Auto

Automatically-generated unique identifiers.

`Auto` field values are auto-generated unless explicitly supplied. This is the
primary difference between `Auto` and `Identifier` fields. Since they are
always auto-generated, `Auto` fields cannot be marked `required=True`.

**Optional Arguments**

- **`increment`**: Auto-increment field value. Defaults to `False`. If set, the
value is expected to be generated by the database at the time of persistence.

!!!note
    It is necessary for the underlying persistence store to support this
    `increment` feature. You have to set up the database schema accordingly.
    Cross-check with the specific adapter's documentation and your database
    to confirm if the database supports this functionality.

- **`identity_strategy`**: The strategy to use to generate an identity value.
If not provided, the strategy defined at the domain level is used.

- **`identity_function`**: A function that is used to generate the identity
value. If not provided, the function defined at the domain level is used.

- **`identity_type`**: The type of the identity value. If not provided, the
type defined at the domain level is used.

The identity params are useful when constructing an entity whose identity
schema differs from the default.

By default, all entities and aggregates create an `Auto` field named `id`
that represents their unique identifier.

```python hl_lines="10"
{! docs_src/guides/domain-definition/fields/simple-fields/001.py !}
```

```shell hl_lines="4 11"
In [1]: declared_fields(Person)
Out[1]: 
{'name': String(required=True, max_length=50, min_length=2),
 'id': Auto(identifier=True)}

In [2]: p = Person(name='John Doe')

In [3]: p.to_dict()
Out[3]:
{'name': 'John Doe',
 'id': '7d32e929-e5c5-4856-a6e7-1ebf12e6259e'}
```

Identity values are UUIDs by default. You can customize this behavior with
`identity_strategy` and `identity_type` [config attributes](../../configuration.md#domain-configuration-attributes).

The [Identity](../../identity.md) section deep dives into identities in Protean.

## Identifier

An Identifier. The identity type is String type by default, but can be changed
with `identity_type` configuration attribute for all entities, or can be set
per entity with the `identity_type` parameter.

**Optional Arguments**

- **`identity_type`**: The type of the identifier field. If not provided, it
will be picked from the domain configuration. Defaults to `STRING`. Raises
`ValidationError` if the provided identity type is not supported.

```python hl_lines="14"
{! docs_src/guides/domain-definition/fields/simple-fields/008.py !}
```

```shell hl_lines="4"
In [1]: user = User(user_id=1, name="John Doe")

In [2]: user.to_dict()
Out[2]: {'user_id': 1, 'name': 'John Doe', 'subscribed': False}
```

Refer to [Identity](../../identity.md) section for a deep dive into identities
in Protean.
