# ADR-0044: The custom-field extension point is a public `Custom` factory

**Status:** Accepted

**Date:** September 2026

## Context

Protean has a built-in factory for each field type it ships: `String`,
`Integer`, `Decimal`, and so on. Each returns a `FieldSpec`, the declaration
carrier the element model collects. Some types have no Protean factory but
still need Protean's field machinery (`required`, a default, constraints,
adapter reflection). You had no supported way to declare a field over such a
type.

We changed the extension point twice before this decision.

In the first draft (2026-08-31), we wrote the contract against the `base.py`
`Field` descriptor class. A custom field would subclass `Field`, implement
`_cast_to_type` and `as_dict`, and reach adapters through `ResolvedField`. This
does not work. The scalar field types became factory functions returning
`FieldSpec` (in `fields/simple.py`). The element model collects only
`FieldSpec` instances (`resolve_fieldspecs` scans for `isinstance(value,
FieldSpec)`). The element model never collects a plain `Field` subclass
declared on an aggregate, so the subclass never becomes a `ResolvedField`. No
code converts a `Field` subclass into a `ResolvedField`. So `base.py` `Field`
is the wrong extension point for a custom field type.

In the second draft (2026-09-19), we wrote the contract against `FieldSpec`. A
third party would instantiate `FieldSpec` directly over a custom Python type.
This contradicts the ratified surface. The stable-surface page marks direct
`FieldSpec` instantiation as Internal ("FieldSpec is the declaration carrier
the decorators build for you"). A contract telling an author to construct a
`FieldSpec` would promote a name we had just called Internal.

## Decision

The custom-field extension point is a public factory, `Custom`, in the shape of the
`fields/simple.py` scalar factories.

```python
Custom(python_type, *, validators=(), serializers=(), **constraints)
```

- `python_type` is the field's Python type.
- `validators` are the Pydantic validators the type needs to parse a raw value into
  an instance. An arbitrary class has no Pydantic core schema on its own, so in
  practice you need at least one validator. `PlainValidator` is the direct
  choice: it replaces the schema and needs no `arbitrary_types_allowed`. An
  `AfterValidator` in the same list runs after the parse, which is the
  "validators" stage of the guaranteed order (empty, then choices, then cast,
  then validators).
- `serializers` are the Pydantic serializers (for example `PlainSerializer`) for
  Pydantic's own `model_dump`.
- `**constraints` are the usual field constraints, passed straight to `FieldSpec`.

`Custom` builds a `FieldSpec` over `python_type` with `field_kind="custom"` and
passes the validators and serializers to that `FieldSpec` separately. When
`FieldSpec.resolve_type` builds the annotation, it attaches the validators and
serializers as `Annotated[python_type, *validators, *serializers]`. The author
never instantiates `FieldSpec`. `Custom` ships **Stable**.

`FieldSpec` stays **Internal**. The `base.py` `Field` descriptor engine stays
**Provisional**, unchanged and out of scope. That engine covers association
fields, `Nested` and `Method`.

An adapter reads serialized values through `ResolvedField.as_dict`, which is
the serialization boundary. The adapter does not use the Pydantic serializer.
`as_dict` calls a value's `to_dict()` when the value has that method. So to
meet the contract, you implement `to_dict()` on your custom type. `to_dict()`
returns the stored form for persistence and event payloads. The custom type's
parser must accept that stored form back, so the value round-trips through
save, reload, and event replay. Serializing through `to_dict()` needs no change
to the Provisional `ResolvedField`.

Fact-event generation needed one framework change. A fact event is a Pydantic
model built from the aggregate's resolved fields. The fact-event builder read
only the bare annotation (`finfo.annotation`), which for a custom type is the
raw class with no schema. The fact-event builder now re-attaches the field's
Pydantic metadata for custom fields (`Annotated[annotation, *finfo.metadata]`),
so the validators and serializers carry onto the fact event. Built-in fields
are unaffected: they have a native schema, so their metadata is still left off
the fact event as before.

The existing way to bypass Protean's field machinery stays the same. When a
custom type needs no Protean machinery, you declare it as a raw
`Annotated[CustomType, Field(...)]`. Protean passes that declaration through to
Pydantic untouched (documented in the defining-fields guide). The reference
page states both paths and when each applies.

## Consequences

- A third party can declare a field over any Python type from the reference page
  alone, using `Custom` plus the Pydantic validators and serializers the type needs.
- A reusable conformance harness
  (`protean.integrations.pytest.custom_field_conformance.run_custom_field_conformance`)
  runs a `Custom` field against the whole contract: the validation order, the
  `ResolvedField` reflection, and a serialize, persist, reload, and event-replay
  round-trip. The worked example on the reference page is verified by running it.
- We promote `Custom` in this change. `Field` and `FieldBase` stay Provisional.
  They form the more advanced descriptor extension point, which keeps its own
  contract and stays unpromoted here.
- Choices combined with a custom type degenerate: `resolve_type` would replace the
  annotation with a `Literal` of the choice values, discarding the custom type.
  So `Custom` rejects `choices` at declaration with an `IncorrectUsageError`
  rather than building a field that silently stores the raw primitive and never
  calls the parser. `Custom` is for types that parse and validate their values.
  For a closed vocabulary of primitive values, use `String(choices=...)` or
  `Status`.
- `Custom` stores the custom type's validators and serializers on the
  `FieldSpec` and leaves `python_type` as the bare type. `FieldSpec` resolves
  the type-specific constraints (`max_length`, decimal precision and scale) off
  `python_type`. An `Annotated` wrapper on `python_type` hides the base type
  from those checks, so `FieldSpec` dropped the constraint and raised no error.
  `resolve_type` re-attaches the metadata when it builds the annotation.
- A custom value is serialized at the shared adapter boundary (`_entity_to_dict`)
  and in query filters, both through `ResolvedField.as_dict`. The in-memory
  store keeps any Python object, but SQLAlchemy maps an unknown type to a
  string column and Elasticsearch indexes the raw value. Without that
  serialization, the driver rejected the instance on write, and a `unique=True`
  lookup bound the object into the query. A custom field inside an embedded
  value object is covered too: its shadow attribute carries the real field, so
  the same serialization applies. SQLite round-trip tests cover save, reload,
  the stored column value, the duplicate check, and the value-object case.
- The mypy plugin reads `Custom`'s type from its first argument, the way it
  already does for `HasOne`, `HasMany` and `ValueObject`: `Custom(Color)` is
  `Color | None` and `Custom(Color, required=True)` is `Color`. Without it the
  factory showed up as `FieldSpec` and every attribute read off a custom field
  was mistyped.
- A custom default is serialized through `as_dict` before it goes into the IR.
  A custom default is an instance of the custom type. The IR is written out as
  JSON and hashed into the canonical baselines.
- A custom field emits `"kind": "custom"` in the IR, so the IR schema carries a
  `field_custom` definition for it. Without that definition every IR document from a
  domain holding one custom field failed schema validation.
- The IR type name for a custom field comes from the field's Python type, not from
  a blanket fallback: `Custom(int, ...)` is `Integer`, `Custom(float, ...)` is
  `Float`. The JSON Schema, Avro and Protobuf generators read that name, so the
  blanket `String` would have published an integer field as a string. The
  builder cannot know the stored shape of a class of the author's own, because
  the class's `to_dict()` produces that shape. So a custom field over such a
  class keeps the `String` fallback, and the reference page tells you to make
  the class serialize to a string.
