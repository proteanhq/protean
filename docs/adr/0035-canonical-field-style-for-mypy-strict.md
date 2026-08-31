# ADR-0035: Canonical field-declaration style for mypy-strict domains

**Status:** Accepted

**Date:** August 2026

## Context

Protean lets you declare a field in more than one style. The style the docs teach and most domains use puts the field spec in the annotation slot:

```python
class Book:
    title: String(required=True)
```

This reads like a schema and works at runtime, because the metaclass reads the class annotations to find the fields. mypy sees something else. `String(required=True)` is a function call, and a function call is not a type, so under `mypy --strict` every such line is an error ("Cannot use a function call in a type annotation"), and constructing the element by keyword fails because mypy never learned the fields. The mypy plugin cannot recover the type either. mypy discards the call at parse time, before any plugin hook runs, so the best a plugin can do for this style is suppress the error and leave the field typed as a permissive `Any`.

ADR-0018 set the direction that the framework itself passes `mypy --strict`. This ADR settles the style a downstream domain should use to get a clean strict run with real field types, one where mypy catches a wrong assignment on a domain object.

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

The typed-annotation style is the shape Pydantic and SQLAlchemy 2.0 use. The Python type lives where a type belongs, the field spec carries the validation config, and the two check each other: a wrong base type (`count: int = String(...)`) or a wrong nullability (`name: str = String()` on an optional field) is a mypy error.

## Decision

The typed-annotation style is the canonical way to declare a field in a mypy-clean Protean domain. A required field is `name: str = String(required=True)`. An optional field is `name: str | None = String()`, because Protean fields are optional by default.

The docs teach this style. The assignment style stays supported and type-checks the same way.

The annotation-only style (`name: String(...)`) stays supported for existing code and is made strict-clean by the mypy plugin. Its fields resolve to a permissive type, so it passes strict without the field-level checking the typed-annotation style gives. It carries no deprecation.

The `required` flag stays as it is. A field is nullable in the annotation with `| None`, and required in the field call with `required=True`. Whether the field call should shed what the annotation already expresses, the field kind and nullability and container content type, is a separate field-API question aimed at 1.0, tracked in issue #1498. This ADR leaves the field API unchanged.

## Consequences

- A domain written in the typed-annotation style passes `mypy --strict` with real field types. mypy catches a wrong assignment to a field, a wrong keyword at construction, and a missing required field.
- The annotation and the field call check each other. A type that disagrees with the factory, or a non-optional annotation on an optional field, is a mypy error at the declaration.
- Optionality is written in the annotation. An optional field needs `| None`, and `name: str = String()` on an optional field is an error. This is stricter than the annotation-only style, and it keeps the annotation and the runtime nullability aligned.
- The docs change. The current examples use the annotation-only style, so the canonical examples move to the typed-annotation style.
- Existing code keeps working. The annotation-only style still runs and now passes strict, at the permissive-type level.

## Alternatives Considered

The annotation-only style as canonical was rejected. It cannot carry real field types under any mypy plugin, because the type is gone before the plugin runs, so "strict passes" would mean fields typed `Any`. For a framework whose pitch is always-valid domains, the typed layer should hold real types.

The assignment style as canonical was considered. It type-checks with full field types and needs no new plugin work. The typed-annotation style was chosen over it because the Python type reads inline in the source, and the style matches Pydantic and SQLAlchemy 2.0, the ecosystem Protean's users already work in.

A field-API redesign that drops the redundant flags, a single `field()` driven by the annotation in the Pydantic shape, was considered and deferred. It is a larger change with a behavioral break, tracked in #1498 and aimed at 1.0.
