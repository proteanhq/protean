# ADR-0044: The custom-field extension point is a public `Custom` factory

**Status:** Accepted

**Date:** September 2026

## Context

Protean has a built-in factory for each field type it ships: `String`, `Integer`,
`Decimal`, and so on. Each returns a `FieldSpec`, the declaration carrier the
element model collects. There was no supported way to declare a field over a type
Protean does not ship a factory for, when that type still needs Protean's field
machinery (`required`, a default, constraints, adapter reflection).

The extension point moved twice before it settled.

The first draft (2026-08-31) specified the contract against the `base.py` `Field`
descriptor class: a custom field would subclass `Field`, implement `_cast_to_type`
and `as_dict`, and reach adapters through `ResolvedField`. This does not work. The
scalar field types became factory functions returning `FieldSpec` (in
`fields/simple.py`), and the element model collects only `FieldSpec` instances
(`resolve_fieldspecs` scans for `isinstance(value, FieldSpec)`). A plain `Field`
subclass declared on an aggregate is never collected, never becomes a
`ResolvedField`, and nothing bridges the two. So `base.py` `Field` is the wrong
extension point for a custom field type.

The second draft (2026-09-19) re-aimed the contract at `FieldSpec`: a third party
would instantiate `FieldSpec` directly over a custom Python type. This contradicts
the ratified surface. Direct `FieldSpec` instantiation is Internal on the
stable-surface page ("FieldSpec is the declaration carrier the decorators build for
you"), so a contract that tells an author to construct one would promote a name we
had just called Internal.

## Decision

The custom-field extension point is a public factory, `Custom`, in the shape of the
`fields/simple.py` scalar factories.

```python
Custom(python_type, *, validators=(), serializers=(), **constraints)
```

- `python_type` is the field's Python type.
- `validators` are the Pydantic validators the type needs to parse a raw value into
  an instance. An arbitrary class has no Pydantic core schema on its own, so at
  least one validator is required in practice; `PlainValidator` is the direct choice
  because it replaces the schema and needs no `arbitrary_types_allowed`. An
  `AfterValidator` in the same list runs after the parse, which is the "validators"
  stage of the guaranteed order (empty, then choices, then cast, then validators).
- `serializers` are the Pydantic serializers (for example `PlainSerializer`) for
  Pydantic's own `model_dump`.
- `**constraints` are the usual field constraints, passed straight to `FieldSpec`.

`Custom` builds `Annotated[python_type, *validators, *serializers]` and hands it to
`FieldSpec` as the resolved type, with `field_kind="custom"`. The author never
instantiates `FieldSpec`. It ships **Stable**.

`FieldSpec` stays **Internal**. The `base.py` `Field` descriptor engine (association
fields, `Nested`, `Method`) stays **Provisional** and out of scope, unchanged.

The serialization boundary an adapter reads is `ResolvedField.as_dict`, not the
Pydantic serializer. `as_dict` calls a value's `to_dict()` when it has one, so the
contract asks the custom type to implement `to_dict()`. That returns the stored
form for persistence and event payloads, and the type's parser must accept that
form back so the value round-trips through save, reload, and event replay. This
needs no change to the Provisional `ResolvedField`.

Fact-event generation needed one framework change. A fact event is a Pydantic model
built from the aggregate's resolved fields, and it read only the bare annotation
(`finfo.annotation`), which for a custom type is the raw class with no schema. The
fact-event builder now re-attaches the field's Pydantic metadata for custom fields
(`Annotated[annotation, *finfo.metadata]`), so the validators and serializers carry
onto the fact event. Built-in fields are unaffected: they have a native schema, so
their metadata is still left off the fact event as before.

The escape hatch is unchanged. A custom type that needs no Protean machinery is
declared as a raw `Annotated[CustomType, Field(...)]` and passed through to Pydantic
untouched (documented in the defining-fields guide). The reference page states both
paths and when each applies.

## Consequences

- A third party can declare a field over any Python type from the reference page
  alone, using `Custom` plus the Pydantic validators and serializers the type needs.
- A reusable conformance harness
  (`protean.integrations.pytest.custom_field_conformance.run_custom_field_conformance`)
  runs a `Custom` field against the whole contract: the validation order, the
  `ResolvedField` reflection, and a serialize, persist, reload, and event-replay
  round-trip. The worked example on the reference page is verified by running it.
- `Custom` is the promotion this issue delivers. `Field` and `FieldBase` stay
  Provisional; the more advanced descriptor extension point they represent keeps its
  own contract and is not promoted here.
- Choices combined with a custom type degenerate: `resolve_type` replaces the
  annotation with a `Literal` of the choice values, discarding the custom type. So
  `Custom` is for types that parse and validate, not for a closed vocabulary of
  primitive values, which `String(choices=...)` or `Status` already cover.
- A custom field emits `"kind": "custom"` in the IR, so the IR schema carries a
  `field_custom` definition for it. Without that definition every IR document from a
  domain holding one custom field failed schema validation.
- The IR type name for a custom field falls back to `String`, because the IR type
  map has no entry for `field_kind="custom"`. This is a display label in the emitted
  IR only; it does not affect persistence or reflection, and the `field_custom`
  schema definition accepts any type name, so naming it properly later needs no
  schema change. A dedicated IR type name for custom fields is left for later.
