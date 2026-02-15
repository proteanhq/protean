# Common Arguments

!!! abstract "Applies to: DDD · CQRS · Event Sourcing"


## `description`

A long form description of the field. This value can be used by database
adapters to provide additional context to a field.

```python hl_lines="9"
{! docs_src/guides/domain-definition/fields/options/009.py !}
```

## `required`

Indicates if the field is required (must have a value). If `True`, the field
is not allowed to be blank. Default is `False`.

```python hl_lines="9"
{! docs_src/guides/domain-definition/fields/options/001.py !}
```

Leaving the field blank or not specifying a value will raise a
`ValidationError`:

```shell hl_lines="4"
In [1]: p = Person()
ERROR: Error during initialization: {'name': ['is required']}
...
ValidationError: {'name': ['is required']}
```

## `identifier`

If True, the field is an identifier for the entity (a la _primary key_
in RDBMS).

```python hl_lines="9"
{! docs_src/guides/domain-definition/fields/options/002.py !}
```

The field is validated to be unique and non-blank:

```shell hl_lines="6 11"
In [1]: from protean.utils.reflection import declared_fields

In [2]: p = Person(email='john.doe@example.com', name='John Doe')

In [3]: declared_fields(p)
Out[3]: {'email': String(identifier=True), 'name': String(required=True)}

In [4]: p = Person(name='John Doe')
ERROR: Error during initialization: {'email': ['is required']}
...
ValidationError: {'email': ['is required']}
```

Aggregates and Entities need at least one field to be marked as an identifier.
If you don’t specify one, Protean will automatically add a field called `id`
to act as the primary identifier. This means that you don’t need to explicitly
set `identifier=True` on any of your fields unless you want to override the
default behavior or the name of the field.

Alternatively, you can use [`Identifier`](./simple-fields.md#identifier) field type for
primary identifier fields.

By default, Protean dynamically generates UUIDs as values of identifier fields
unless explicitly provided. You can customize the type of value accepted with
`identity-strategy` config parameter. More details are in
[Configuration](../../essentials/configuration.md) section.

## `default`

The default value for the field if no value is provided.

This can be a value or a callable object. If callable, the function will be
called every time a new object is created.

```python hl_lines="16"
{! docs_src/guides/domain-definition/fields/options/003.py !}
```

```shell hl_lines="6"
In [1]: post = Post(title='Foo')

In [2]: post.to_dict()
Out[2]: 
{'title': 'Foo',
 'created_at': '2024-05-09 00:58:10.781744+00:00',
 'id': '4f6b1fef-bc60-44c2-9ba6-6f844e0d31b0'}
```

### Mutable object defaults

**IMPORTANT**: The default cannot be a mutable object (list, set, dict, entity
instance, etc.), because the reference to the same object would be used as the
default in all instances. Instead, wrap the desired default in a callable.

For example, to specify a default `list` for `List` field, use a function:

```python hl_lines="12"
{! docs_src/guides/domain-definition/fields/options/004.py !}
```

Initializing an Adult aggregate will populate the defaults correctly:

```shell
In [1]: adult = Adult(name="John Doe")

In [2]: adult.to_dict()
Out[2]: 
{'name': 'John Doe',
 'topics': ['Music', 'Cinema', 'Politics'],
 'id': '14381a6f-b62a-4135-a1d7-d50f68e2afba'}
```

### Lambda expressions

You can use lambda expressions to specify an anonymous function:

```python hl_lines="13"
{! docs_src/guides/domain-definition/fields/options/005.py !}
```

```shell hl_lines="4"
In [1]: dice = Dice()

In [2]: dice.to_dict()
Out[2]: {'sides': 6, 'id': '0536ade5-f3a4-4e94-8139-8024756659a7'}

In [3]: dice.throw()
Out[3]: 3
```

This is a great option when you want to pass parameters to a function.

## `unique`

Indicates if the field values must be unique within the repository. If `True`,
this field's value is validated to be unique among all entities.

```python hl_lines="10"
{! docs_src/guides/domain-definition/fields/options/006.py !}
```

Obviously, this field's integrity is enforced at the database layer when an
entity is persisted. If an entity instance specifies a duplicate value in a
field marked `unique`, a `ValidationError` will be raised:

```shell hl_lines="11"
In [1]: p1 = Person(name='John Doe', email='john.doe@example.com')

In [2]: domain.repository_for(Person).add(p1)
Out[2]: <Person: Person object (id: b2c592d5-bd78-4e1e-a9d1-eea20ab5374a)>

In [3]: p2 = Person(name= 'Jane Doe', email='john.doe@example.com')

In [4]: domain.repository_for(Person).add(p2)
ERROR: Failed saving entity because {'email': ["Person with email 'john.doe@example.com' is already present."]}
...
ValidationError: {'email': ["Person with email 'john.doe@example.com' is already present."]}
```

We will explore more about persistence in Application Layer guide.
<!-- FIXME Add link to database persistence and aggregate lifecycle -->

## `choices`

A set of allowed choices for the field value. When supplied as an `Enum`, the
value of the field is validated to be one among the specified options.

```python hl_lines="9-11 18"
{! docs_src/guides/domain-definition/fields/options/007.py !}
```

The choices are enforced when the field is initialized or updated:

```shell hl_lines="7 13"
In [1]: building = Building(name="Atlantis", floors=3, status="WIP")

In [2]: building.to_dict()
Out[2]: 
{'name': 'Atlantis',
 'floors': 3,
 'status': 'WIP',
 'id': 'c803c763-32d7-403f-b432-8835a258430e'}

In [3]: building.status = "COMPLETED"
ERROR: Error during initialization: {'status': ["Value `'COMPLETED'` is not a valid choice. Must be among ['WIP', 'DONE']"]}
...
ValidationError: {'status': ["Value `'COMPLETED'` is not a valid choice. Must be among ['WIP', 'DONE']"]}
```

## `referenced_as`

The name of the field as referenced in the database or external systems.
Defaults to the field's name.

```python hl_lines="10"
{! docs_src/guides/domain-definition/fields/options/008.py !}
```

Protean will now persist the value under `fullname` instead of `name`.

```shell hl_lines="6 13"
In [1]: from protean.utils.reflection import declared_fields, attributes

In [2]: declared_fields(Person)
Out[2]: 
{'email': String(),
 'name': String(required=True, referenced_as='fullname'),
 'id': Auto(identifier=True)}

In [3]: attributes(Person)
Out[3]: 
{'_version': Integer(default=-1),
 'email': String(),
 'fullname': String(required=True, referenced_as='fullname'),
 'id': Auto(identifier=True)}
```

## `validators`

Additional validators to apply to the field value.

Validators are
[callable `Class` instances](https://docs.python.org/3/reference/datamodel.html#class-instances)
that are invoked whenever a field's value is changed. Protean's `String` field,
for example, has two default validators: `MinLengthValidator` and
`MaxLenghtValidator` classes associated with `min_length` and `max_length`
attributes.

```python hl_lines="9-16 21"
{! docs_src/guides/domain-definition/fields/options/010.py !}
```

If the value fails to satisfy the validation, a `ValidationError` will be
thrown with the custom error message.

```shell hl_lines="9"
In [1]: e = Employee(email="john@mydomain.com")

In [2]: e.to_dict()
Out[2]: {'email': 'john@mydomain.com'}

In [3]: e2 = Employee(email="john@otherdomain.com")
ERROR: Error during initialization: {'email': ['Email does not belong to mydomain.com']}
...
ValidationError: {'email': ['Email does not belong to mydomain.com']}
```

## `error_messages`

Custom error messages for different kinds of errors. If supplied, the default
messages that the field will raise will be overridden. Default error message
keys that apply to all field types are `required`, `invalid`, `unique`, and
`invalid_choice`. Each field may have additional error message keys as
detailed in their documentation.

```python hl_lines="9-12"
{! docs_src/guides/domain-definition/fields/options/011.py !}
```

Now the custom message will be available in `ValidationError`:

```shell hl_lines="4"
In [1]: Building()
ERROR: Error during initialization: {'doors': ['Every building needs doors.']}
...
ValidationError: {'doors': ['Every building needs some!']}
```
