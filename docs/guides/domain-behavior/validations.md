# Basic Validations

There are many hygiene aspects that need to be enforced in a domain's data
and behavior, even before we get to the point of defining a domain's rules.
These basic aspects can be codified in the form of field types and its options,
using in-build validators, or even defining custom validators and attaching
them to a field.

## Field Restrictions

Field restrictions begin with the type of field chosen to represent an
attribute.

```python hl_lines="12-16"
--8<-- "guides/domain-behavior/003.py:10:24"
```

Violating any of these constraints will throw exceptions:

```shell hl_lines="2 3"
In [3]: account = Account(
   ...:     account_number="A1234",
   ...:     account_type="CHECKING",
   ...:     balance=50)
ERROR: Error during initialization...
...
ValidationError: {
    'account_number': ['"A1234" value must be an integer.'],
    'account_type': [
        "Value `'CHECKING'` is not a valid choice. Must be among ['SAVINGS', 'CURRENT']"
    ]
}
```

These validations kick-in even on attribute change, not just during
initialization, thus keeping the aggregate valid at all times.

Every Protean field also has options that help constrain the field value.
For example, we can specify that the field is mandatory with the `required`
option and stores a unique value  with the `unique` option.

The four options to constrain values are:

- **`required`**: Indicates if the field is required (must have a value). If
`True`, the field is not allowed to be blank. Default is `False`.
- **`identifier`**: If True, the field is an identifier for the entity. These
fields are `unique` and `required` by default.
- **`unique`**: Indicates if the field values must be unique within the 
repository. If `True`, this field's value is validated to be unique among
all entities of same category.
- **`choices`**: A set of allowed choices for the field value, supplied as an
`Enum` or `list`.

!!!note
    Note that some constraints, like uniqueness, will only be enforced when the
    element is persisted.


Since `Account.account_number` was declared `required` earlier, skipping it
will throw an exception:

```shell hl_lines="6"
n [5]: account = Account(
   ...:     account_type="SAVINGS",
   ...:     balance=50)
ERROR: Error during initialization: {'account_number': ['is required']}
...
ValidationError: {'account_number': ['is required']}
```

A full-list of field types and their options is available in the
[Fields](../domain-definition/fields/index.md) section.

## In-built Validations

Many field classes in Protean come pre-equipped with basic validations, like
length and value.

For example, `Integer` fields have `min_value` and `max_value` validators,
while `String` fields have `min_length` and `max_length` validators. These
validators are typically activated by supplying them as a parameter during
field initialization.

```python hl_lines="12-16"
--8<-- "guides/domain-behavior/004.py:7:10"
```

Violating these constraints results in an immediate exception:

```shell
In [1]: Person(name="Ho", age=200)
ERROR: Error during initialization:
...
ValidationError: {'name': ['value has less than 3 characters'], 'age': ['value is greater than 120']}
```

A full-list of in-built validators is available in the
[Fields](../domain-definition/fields/index.md) section under each field.


## Custom Validators

You can also add vaidations at the field level by defining custom validators.

```python hl_lines="14-17"
--8<-- "guides/domain-behavior/005.py:10:26"
```

Now, an email address assigned to the field is validated with the custom
regex pattern:

```shell
In [1]: Person(name="John", email="john.doe@gmail.com")
Out[1]: <Person: Person object (id: 659fa079-f93c-4a6d-9b16-19af02ec86ef)>

In [2]: Person(name="Jane", email="jane.doe@.gmail.com")
...
ValueError: Invalid Email Address - jane.doe@.gmail.com
```