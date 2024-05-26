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

Automatically-generated unique identifiers. By default, all entities and
aggregates create an `Auto` field named `id` that represents their unique
identifier.

**Optional Arguments**

- **`increment`**: Auto-increment field value. Defaults to `False`. Only valid
when `identity_type` is `INTEGER` and `identity_strategy` is set to `DATABASE`.

!!!note
    Not all databases support this `increment` feature. Cross-verify with the
    Protean adapter's documentation to confirm if this functionality is
    supported.

You cannot supply values explicitly to Auto fields - they are self-generated.
If you want to supply values, use [`Identifier`](#identifier) fields.

```python hl_lines="10"
{! docs_src/guides/domain-definition/fields/simple-fields/001.py !}
```

By default, Protean depends on UUIDs as identifier values. You can use the
`identity_type` config attributes to customize this behavior and choose
another type (like integer values). 

```shell hl_lines="6"
In [1]: p = Person(name='John Doe')

In [2]: p.to_dict()
Out[2]:
{'name': 'John Doe',
 'id': '7d32e929-e5c5-4856-a6e7-1ebf12e6259e'}
```

Refer to [Identity](../identity.md) section for a deep dive into identities
in Protean.

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

Refer to [Identity](../identity.md) section for a deep dive into identities
in Protean.
