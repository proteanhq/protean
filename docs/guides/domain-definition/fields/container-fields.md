# Container Fields

## `ValueObject`

Represents a field that holds a value object. This field is used to embed a
Value Object within an entity.

**Arguments**

- **`value_object_cls`**: The class of the value object to be embedded.

```python hl_lines="7-15 20"
{! docs_src/guides/domain-definition/fields/container-fields/003.py !}
```

You can provide an instance of the Value Object as input to the value object
field:

```shell hl_lines="2 8"
In [1]: account = Account(
   ...:     balance=Balance(currency="USD", amount=100.0),
   ...:     name="Checking"
   ...: )

In [2]: account.to_dict()
Out[2]: 
{'balance': {'currency': 'USD', 'amount': 100.0},
 'name': 'Checking',
 'id': '513b8a78-e00f-45ce-bb6f-11ef0cccbec6'}
```

## `List`

A field that represents a list of values.

**Optional Arguments**

- **`content_type`**: The type of items in the list. Defaults to `String`.
Accepted field types are `Boolean`, `Date`, `DateTime`, `Float`, `Identifier`,
`Integer`, `String`, and `Text`.
- **`pickled`**: Whether the list should be pickled when stored. Defaults to
`False`.

!!!note
    Some database implementations (like Postgresql) can store lists by default.
    You can force it to store the pickled value as a Python object by
    specifying `pickled=True`. Databases that don’t support lists simply store
    the field as a python object.

```python hl_lines="10"
{! docs_src/guides/domain-definition/fields/container-fields/001.py !}
```

The value is provided as a `list`, and the values in the `list` are validated
to be of the right type.

```shell hl_lines="6 12"
In [1]: user = User(email="john.doe@gmail.com", roles=['ADMIN', 'EDITOR'])

In [2]: user.to_dict()
Out[2]: 
{'email': 'john.doe@gmail.com',
 'roles': ['ADMIN', 'EDITOR'],
 'id': '582d946b-409b-4b15-b3be-6a90284264b3'}

In [3]: user2 = User(email="jane.doe@gmail.com", roles=[1, 2])
ERROR: Error during initialization: {'roles': ['Invalid value [1, 2]']}
...
ValidationError: {'roles': ['Invalid value [1, 2]']}
```

### List of Value Objects

A `List` field can even hold a list of `ValueObject` instances. The content of
the `List` will be persisted as a list of dicts, so the field will behave
essentially like `List(Dict())` when it comes to persistence. However, it will
have the added benefit of a validation structure of content within the List.

```python hl_lines="7-12 19"
{! docs_src/guides/domain-definition/fields/container-fields/004.py !}
```

```shell
In [1]: order = Order(
   ...:         customer=Customer(
   ...:             name="John Doe",
   ...:             email="john@doe.com",
   ...:             addresses=[
   ...:                 Address(street="123 Main St", city="Anytown", state="CA", country="USA"),
   ...:                 Address(street="321 Side St", city="Anytown", state="CA", country="USA"),
   ...:             ],
   ...:         )
   ...:     )

In [2]: order.to_dict()
Out[2]: 
{'customer': {'name': 'John Doe',
  'email': 'john@doe.com',
  'addresses': [{'street': '123 Main St',
    'city': 'Anytown',
    'state': 'CA',
    'country': 'USA'},
   {'street': '321 Side St',
    'city': 'Anytown',
    'state': 'CA',
    'country': 'USA'}],
  'id': 'f5c5a750-e9fe-47db-877e-44b7c0ca1dfc'},
 'id': '4a9538bf-1eb1-4621-8ced-86bcc4362a51'}

In [3]: domain.repository_for(Order).add(order)
Out[3]: <Order: Order object (id: 4a9538bf-1eb1-4621-8ced-86bcc4362a51)>

In [4]: retrieved_order = domain.repository_for(Order).get(order.id)

In [5]: len(retrieved_order.customer.addresses)
Out[5]: 2
```

Note that unlike `HasMany` fields, you have to supply a new entire list of
Value Objects if you want to update the field. Appendind to the list will not
work.

```shell
In [6]: retrieved_order.customer.addresses.append(
   ...:     Address(street="456 Side St", city="Anytown", state="CA", country="USA")
   ...: )

In [7]: domain.repository_for(Order).add(retrieved_order)
Out[7]: <Order: Order object (id: 4a9538bf-1eb1-4621-8ced-86bcc4362a51)>

In [8]: updated_order = domain.repository_for(Order).get(order.id)

In [9]: len(updated_order.customer.addresses)
Out[9]: 2
# This did not work!
In [10]: updated_order.customer.addresses = [
    ...:     Address(street="123 Main St", city="Anytown", state="CA", country="USA"),
    ...:     Address(street="321 Side St", city="Anytown", state="CA", country="USA"),
    ...:     Address(street="456 Side St", city="Anytown", state="CA", country="USA"),
    ...: ]

In [11]: domain.repository_for(Order).add(updated_order)
Out[11]: <Order: Order object (id: 4a9538bf-1eb1-4621-8ced-86bcc4362a51)>

In [12]: refreshed_order = domain.repository_for(Order).get(order.id)

In [13]: len(refreshed_order.customer.addresses)
Out[13]: 3
# This worked!
```

## `Dict`

A field that represents a dictionary.

**Optional Arguments**

- **`pickled`**: Whether the dict should be pickled when stored. Defaults to
`False`.

```python hl_lines="10"
{! docs_src/guides/domain-definition/fields/container-fields/002.py !}
```

A regular dictionary can be supplied as value to payload:


```shell hl_lines="3 9"
In [1]: event=UserEvent(
   ...:     name="UserRegistered",
   ...:     payload={'name': 'John Doe', 'email': 'john.doe@example.com'}
   ...: )

In [2]: event.to_dict()
Out[2]: 
{'name': 'UserRegistered',
 'payload': {'name': 'John Doe', 'email': 'john.doe@example.com'},
 'id': '44e9143f-f4a6-40da-9128-4b6c013420d4'}
```

!!!note
    Some database implementations (like Postgresql) can store dicts as JSON
    by default. You can force it to store the pickled value as a Python object
    by specifying pickled=True. Databases that don’t support lists simply store
    the field as a python object.
