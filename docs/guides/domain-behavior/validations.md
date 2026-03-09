# Basic Validations

<span class="pathway-tag pathway-tag-ddd">DDD</span> <span class="pathway-tag pathway-tag-cqrs">CQRS</span> <span class="pathway-tag pathway-tag-es">ES</span>

A core DDD principle is that domain objects should be **always valid** — it
should be impossible to construct or mutate an aggregate, entity, or value
object into a state that violates its rules. Protean enforces this guarantee
starting at the field level: every field declaration carries constraints that
are checked automatically on construction and on every subsequent assignment.

Field-level validation is the **first layer** of a broader validation
architecture. Protean organizes validation into four layers, each catching
a different category of invalid state:

| Layer | What it validates | Where it lives |
|-------|-------------------|----------------|
| **1 — Field constraints** | Type, format, range, required | Field declarations (this guide) |
| **2 — Value object invariants** | Concept-level rules (e.g. email format) | [`@invariant.post` on VOs](invariants.md) |
| **3 — Aggregate invariants** | Business rules, cross-field consistency | [`@invariant` on aggregates](invariants.md) |
| **4 — Handler/service guards** | Authorization, cross-aggregate checks | [Command handlers](../change-state/command-handlers.md), [domain services](domain-services.md) |

Each layer trusts the layers below it and adds what they don't cover. This
guide focuses on Layer 1 — field constraints, built-in validators, and custom
validators. For the complete picture, see the
[Validation Layering](../../patterns/validation-layering.md) pattern.

## Field Restrictions

Field restrictions begin with the type of field chosen to represent an
attribute.

```python hl_lines="12-15"
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

These validations kick in even on attribute change, not just during
initialization, thus keeping the aggregate valid at all times.

```shell
In [1]: account = Account(account_number=1234, account_type="SAVINGS", balance=500.0)

In [2]: account.account_type = "CHECKING"
...
ValidationError: {
    'account_type': [
        "Value `'CHECKING'` is not a valid choice. Must be among ['SAVINGS', 'CURRENT']"
    ]
}
```

Every Protean field also has options that help constrain the field value.
For example, we can specify that the field is mandatory with the `required`
option and stores a unique value with the `unique` option.

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

A full list of field types and their options is available in the
[Fields](../../reference/fields/index.md) section.

## In-built Validations

Many field classes in Protean come pre-equipped with basic validations, like
length and value.

For example, `Integer` fields have `min_value` and `max_value` validators,
while `String` fields have `min_length` and `max_length` validators. These
validators are typically activated by supplying them as a parameter during
field initialization.

```python hl_lines="3-4"
--8<-- "guides/domain-behavior/004.py:7:10"
```

Violating these constraints results in an immediate exception:

```shell
In [1]: Person(name="Ho", age=200)
ERROR: Error during initialization:
...
ValidationError: {'name': ['value has less than 3 characters'], 'age': ['value is greater than 120']}
```

Under the hood, these parameters create built-in validator instances from
`protean.fields.validators` — `MinLengthValidator`, `MaxLengthValidator`,
`MinValueValidator`, `MaxValueValidator`, and `RegexValidator`. You rarely need
to use them directly, but they are available if you need to compose validators
programmatically.

A full list of in-built validators is available in the
[Fields](../../reference/fields/index.md) section under each field.


## Custom Validators

You can also add validations at the field level by defining custom validators.
A validator is any callable class that accepts a value and raises `ValueError`
if the value is invalid:

```python hl_lines="14-16"
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

You can attach multiple validators to a single field with the `validators`
list. Protean runs all of them in order, and the first failure stops
evaluation and raises the error.

For more details on the `validators` field option and the `error_messages`
option for customizing error text, see the
[Common Arguments](../../reference/fields/arguments.md#validators) reference.

!!!note
    For domain-concept validation (e.g. "an email must have a valid format"),
    consider using a [value object](../domain-definition/value-objects.md) with
    an invariant (Layer 2) instead of a field-level validator. Value objects are
    reusable across aggregates and make the concept explicit in your domain
    model. See [Validation Layering](../../patterns/validation-layering.md) for
    guidance on choosing the right layer.

## How It Works

Every aggregate, entity, and value object validates field assignments
automatically:

1. **On construction**: Protean validates all fields when the object is created.
   After field validation passes, any `@invariant.post` methods run.
2. **On attribute assignment**: Every `self.field = value` goes through
   `__setattr__`, which triggers field validation. If the value doesn't match
   the field's type or constraints, a `ValidationError` is raised immediately
   — the assignment never takes effect.

This means an aggregate can never hold an invalid field value, even
momentarily. The "always valid" guarantee is enforced at the Python runtime
level, not just at persistence time.

---

!!! tip "See also"
    **Deep dive:** [The Always-Valid Domain](../../concepts/philosophy/always-valid.md) — The complete story of how Protean's four validation layers work together to guarantee your domain objects are never invalid.

    **Concept overview:** [Invariants](../../concepts/foundations/invariants.md) — The foundational concept of keeping domain objects always valid.

    **Related guides:**

    - [Invariants](invariants.md) — Business rules that enforce cross-field consistency (Layers 2-3).
    - [Aggregate Mutation](aggregate-mutation.md) — How state changes trigger validation.

    **Patterns:** [Validation Layering](../../patterns/validation-layering.md) — Choosing the right validation layer for each kind of rule.
