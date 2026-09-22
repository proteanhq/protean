# Custom Fields

!!! abstract "Applies to: DDD · CQRS · Event Sourcing"

`Custom` builds a field over a Python type Protean has no built-in factory for,
when the type still needs Protean's field machinery: `required`, a default,
constraints, or adapter mapping. You supply the type and the Pydantic objects
that parse a raw value into it and render it back; Protean wires them into the
same field pipeline every built-in field uses.

If the type needs none of that, you do not need `Custom`. Declare it as a raw
`Annotated[YourType, Field(...)]` and Pydantic handles it directly. See the
[raw Pydantic style](defining-fields.md#raw-pydantic-style) in the defining-fields
guide. Reach for `Custom` when you want the field to be `required`, carry a
default, or reflect through `ResolvedField` to an adapter the way the built-in
fields do.

## Signature

```python
Custom(python_type, *, validators=(), serializers=(), **constraints)
```

- **`python_type`**: the field's Python type (any class).
- **`validators`**: the Pydantic validators that parse a raw value into the type.
  An arbitrary class has no Pydantic schema on its own, so supply at least a
  `PlainValidator` that builds an instance. Add an `AfterValidator` to run a check
  after the parse (this is the "validators" stage of the order below).
- **`serializers`**: the Pydantic serializers (for example `PlainSerializer`) that
  render an instance back to a plain value for `model_dump`.
- **`**constraints`**: the usual field constraints (`required`, `default`,
  `unique`, `description`, `min_value`/`max_value`, and so on), passed straight to
  the field.

## A worked example

A `Color` type stored as a `#RRGGBB` hex string. It parses a raw string into a
`Color`, and implements `to_dict()` so it round-trips through persistence and
events:

```python
--8<-- "guides/domain-definition/fields/custom-fields/001.py:type"
```

Declare the field with `Custom`, passing the parser and serializer the type needs:

```python
--8<-- "guides/domain-definition/fields/custom-fields/001.py:field"
```

`brand` now behaves like any other field: `Palette(name="sky", brand="#3366ff")`
parses the string into a `Color`, and `brand=Color("#3366FF")` passes an existing
instance straight through.

## The validation order is guaranteed

A field runs its checks in a fixed order, and `Custom` inherits it unchanged:

1. **empty**: an optional field left unset resolves to its default, or to `None`
   when it has none, and short-circuits here. The parser is never asked to build
   an instance out of nothing.
2. **cast**: the value is parsed into the type. For `Custom`, this is the
   `PlainValidator` you supplied.
3. **validators**: post-cast checks run on the parsed value. For `Custom`, these
   are any `AfterValidator` objects you passed in `validators`.

So an `AfterValidator` always sees a parsed instance, never a raw value, and a
missing optional value never reaches your parser.

!!! warning "`Custom` rejects `choices`"

    Passing `choices` to `Custom` raises `IncorrectUsageError` at declaration.
    A choice set makes Protean replace the field's type with a `Literal` of the
    choice values, which would discard your custom type: the field would store
    the raw primitive and your parser would never run. `Custom` is for a type
    that parses and validates, not for a closed vocabulary of primitive values.
    For that, use `String(choices=...)` or `Status`.

## The serialization boundary adapters read

Adapters and the persistence and event paths do not read your Pydantic serializer.
They read `ResolvedField.as_dict`, which turns a stored value into a JSON-compatible
form. `as_dict` calls a value's `to_dict()` when it has one, so **implement
`to_dict()` on your type** and the field round-trips through save, reload, and
event replay. The `serializers` you pass to `Custom` cover Pydantic's own
`model_dump`; `to_dict()` covers Protean's persistence.

The value your `to_dict()` returns must be something your parser accepts back. In
the example, `to_dict()` returns the hex string and `parse_color` accepts a hex
string, so a `Color` saved as `"#3366FF"` reloads as the same `Color`.

That serialized form is what the store holds, so it is also what a query compares
against. Protean serializes a custom value in a filter the same way, so both
`filter(brand=Color("#3366FF"))` and `filter(brand="#3366FF")` find the record,
and `unique=True` catches a duplicate.

The generated schemas (JSON Schema, Avro, Protobuf) read the field's Python type.
A custom field over a primitive is typed as that primitive: `Custom(int, ...)` is
an integer. A custom field over a class of your own is typed as a string, because
Protean cannot know what your `to_dict()` returns. So if you publish schemas, have
`to_dict()` return a string, as the `Color` example does.

## Prove your field with the conformance suite

Protean ships a reusable check your `Custom` field can run against itself. Give it
the field, a raw value that should parse, the value it should parse to, and a raw
value it should reject:

```python
from pydantic import PlainSerializer, PlainValidator

from protean.fields import Custom
from protean.integrations.pytest.custom_field_conformance import (
    run_custom_field_conformance,
)


def test_color_field_conformance():
    field = Custom(
        Color,
        validators=[PlainValidator(parse_color)],
        serializers=[PlainSerializer(lambda c: c.hex, return_type=str)],
        required=True,
    )
    run_custom_field_conformance(
        field,
        valid_input="#3366ff",
        expected=Color("#3366FF"),
        invalid_input="not-a-color",
    )
```

The harness declares a throwaway aggregate carrying the field, then asserts the
whole contract: the validation order, the `ResolvedField` reflection, and a
serialize, persist, reload, and event-replay round-trip. See
[Conformance testing](../testing/conformance.md) for details.
