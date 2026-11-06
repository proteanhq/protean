# ADR-0038: Canonical field-declaration style for mypy-strict domains

**Status:** Accepted

**Date:** August 2026

## Context

Protean lets you declare a field in more than one style. Most domains use the
style the docs teach, which puts the field spec in the annotation slot:

```python
class Book:
    title: String(required=True)
```

This reads like a schema and works at runtime, because the metaclass reads the
class annotations to find the fields. mypy sees something else.
`String(required=True)` is a function call, and a function call is not a type,
so under `mypy --strict` every such line is an error ("Cannot use a function
call in a type annotation"). mypy also rejects keyword construction of the
element, because it never learned the fields. The mypy plugin cannot recover
the type either. mypy discards the call at parse time, before any plugin hook
runs. For this style, a plugin can at best suppress the error and leave the
field typed as a permissive `Any`.

Under the type-safety adoption strategy (ADR-0018), the framework itself passes
`mypy --strict`. This ADR is about the style a downstream domain should use for
a clean strict run with real field types. With real field types, mypy catches a
wrong assignment on a domain object.

Two styles already type-check cleanly today. The assignment style writes the field as a value:

```python
class Book:
    title = String(required=True)      # mypy sees: str
```

The typed-annotation style writes the Python type in the annotation and the field spec as the value:

```python
class Book:
    title: str = String(required=True)          # required, non-null
    subtitle: str | None = String()             # optional, nullable
```

The typed-annotation style is the shape Pydantic and SQLAlchemy 2.0 use. In
this style the Python type is in the annotation, and the field spec holds the
validation config. The two check each other: a wrong base type (`count: int =
String(...)`) or a wrong nullability (`name: str = String()` on an optional
field) is a mypy error.

## Decision

The typed-annotation style is the canonical way to declare a field in a mypy-clean Protean domain. A required field is `name: str = String(required=True)`. An optional field is `name: str | None = String()`, because Protean fields are optional by default.

The docs teach the typed-annotation style. The assignment style stays supported
and type-checks the same way.

The annotation-only style (`name: String(...)`) stays supported for existing code and is made strict-clean by the mypy plugin. Its fields resolve to a permissive type, so it passes strict without the field-level checking the typed-annotation style gives. It carries no deprecation.

The `required` flag stays as it is. A field is nullable in the annotation with
`| None`, and required in the field call with `required=True`. Issue #1498
tracks a separate field-API question, aimed at 1.0. The question is whether the
field call should drop what the annotation already expresses: the field kind,
the nullability and the container content type. This ADR leaves the field API
unchanged.

## Consequences

- A domain written in the typed-annotation style passes `mypy --strict` with real field types. mypy catches a wrong assignment to a field, a wrong keyword at construction, and a missing required field.
- The annotation and the field call check each other. mypy reports an error at
  the declaration for a type that disagrees with the factory, or for a
  non-optional annotation on an optional field.
- Optionality is written in the annotation. An optional field needs `| None`, and `name: str = String()` on an optional field is an error. This is stricter than the annotation-only style, and it keeps the annotation and the runtime nullability aligned.
- The docs change. The current examples use the annotation-only style, so the canonical examples move to the typed-annotation style.
- Existing code keeps working. The annotation-only style still runs and now passes strict, at the permissive-type level.

## Alternatives Considered

The annotation-only style as canonical was rejected. The annotation-only style
cannot carry real field types under any mypy plugin, because the type is gone
before the plugin runs. In that style, "strict passes" would mean fields typed
`Any`. For a framework whose pitch is always-valid domains, the typed layer
should hold real types.

The assignment style as canonical was considered. The assignment style
type-checks with full field types. It needs no new plugin work. The
typed-annotation style was chosen over the assignment style because the Python
type reads inline in the source. The typed-annotation style also matches
Pydantic and SQLAlchemy 2.0, the ecosystem Protean's users already work in.

The maintainers considered and deferred a field-API redesign that drops the
redundant flags. The redesign is a single `field()` driven by the annotation,
in the Pydantic shape. The redesign is a larger change with a behavioral break.
Issue #1498 tracks it, aimed at 1.0.
