# Identity

Protean generates identities close to the point of element creation. Generating
an identity at the point of creation is a best practice as it ensures
consistency, aligns with domain rules, simplifies logic, and supports
distributed systems.

Protean's design philosophy requires all invariants
to be satisfied from the get-go - generating identities on element creation
helps fulfill this goal.

## Configuration

Identity options are specified at the Domain level with
[configuration attributes](./configuration.md#domain-configuration-attributes). A combination of
identity strategy and identity type work together to generate identity values.

```toml
# domain.toml
...
identity_strategy="uuid"
identity_type="string"
...
```

### Strategy

The strategy for generating identity values.

Since aggregates are essentially consistency boundaries, it is best to generate
identities without external dependencies. UUIDs are the best mechanism to
accomplish this without a central coordinating system, and are especially useful
in distributed systems.

The following strategies are supported for identity generation:

- **uuid** - Identity is a uuid4 identifier. This is the default and preferred
strategy.
- **function** - A function is invoked to generate identity values, supplied
as [`identity_function`](./compose-a-domain/index.md#identity_function) when constructing
the domain object.

### Type

The type of the generated identity value. Supported identity types are
`integer`, `string`, and `uuid`. Default is `string`.

- **`string`** - Everything that is castable to a string value
is accepted. So UUIDs, integers, and string values like `user-234232234`
are allowed.

- **`integer`** - anything that is castable to an integer
is accepted. Strings like `1` are allowed. So are UUIDs because they can be
represented as integer values.

```python
In [1]: import uuid

In [2]: uuid.uuid4().int
Out[2]: 154702789254628181204690697941965130883
```

- **`uuid`** - A uuid object is allowed. Many databases have
inbuilt support for UUIDs and this option leverages it for performance. For
example, PostgreSQL has a built-in `UUID` data type that can store a 128-bit
value, typically represented as a 36-character string.

!!!note
    Identity Strategy and Identity Type values have to be configured to
    work together. For example, the values returned by configured
    `identity_function` has to match the type configured in `identity_type`.

## Fields

Protean can hold identity values in two field types: `Auto` and `Identifier`.

`Auto` and `Identifier` fields are the same - they hold identities. The only
difference is that values of `Auto` fields are auto-generated when not supplied.

Each entity and aggregate in Protean has to have a unique identity field. A
field can be designated as the identity by setting `identifier=True`
in its properties.

```py hl_lines="9"
{! docs_src/guides/composing-a-domain/023.py !}
```

```shell hl_lines="4 9 15"
In [1]: from protean.reflection import declared_fields, attributes

In [2]: declared_fields(User)
Out[2]: {'user_id': Auto(identifier=True), 'name': String(required=True)}

In [3]: attributes(User)
Out[3]: 
{'_version': Integer(default=-1),
 'user_id': Auto(identifier=True),
 'name': String(required=True)}

In [4]: user = User(name="John Doe")

In [5]: user.to_dict()
Out[5]: {'user_id': '9cf4ddc4-2919-4021-bd1a-c8083b5fdda7', 'name': 'John Doe'}
```

### Automatic Identity field

When an identity field is not supplied, an `Auto` field called `id` is
automatically added to the entity.

```py
{! docs_src/guides/domain-definition/fields/simple-fields/001.py !}
```

```shell hl_lines="6"
In [1]: from protean.reflection import declared_fields

In [2]: declared_fields(Person)
Out[2]: 
{'name': String(required=True, max_length=50, min_length=2),
 'id': Auto(identifier=True)}
```

### No Composite keys

Protean does not support composite keys. A `NotSupportedError` is thrown when
multiple identifier fields are found.

```shell hl_lines="5 6"
In [9]: from protean.fields import Auto, Identifier

In [10]: @domain.aggregate
    ...: class Order:
    ...:     order_id = Auto(identifier=True)
    ...:     customer_id = Identifier(identifier=True)
    ...: 
---------------------------------------------------------------------------
...
NotSupportedError: {'_entity': ['Multiple identifier fields found in entity Order. Only one identifier field is allowed.']}
```

## Element-level Identity Customization

The identity of an aggregate or entity element can be customized by explicit
configuration of an `Auto` or `Identifier`:

```python hl_lines="9-10 15-20"
{! docs_src/guides/composing-a-domain/024.py !}
```

1. A custom function that generates identity in the form of epoch time
2. Arguments to `Auto` field control how the identity is generated.

```shell hl_lines="4"
In [1]: user = User(name="John Doe")

In [2]: user.to_dict()
Out[2]: {'user_id': 1718139167980, 'name': 'John Doe'}
```
