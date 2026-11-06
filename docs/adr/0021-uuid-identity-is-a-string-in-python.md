# ADR-0021: A uuid identity is a string in Python

**Status:** Accepted

**Date:** July 2026

## Context

Protean's identity system supports three identity types, selected by
`identity_type` in configuration: `string`, `integer`, and `uuid`. The value is
produced by a single generator and injected as the aggregate's (or entity's)
`id` field when no identifier is declared explicitly.

Before this decision, the two identity paths produced different types under
`identity_type = "uuid"`. The **auto-injected** `id` field held a native
`uuid.UUID` object, while an **explicitly declared** `Auto(identifier=True,
identity_type="uuid")` field coerced its value to a `str`. The auto-injected
path is the default, so most code received the native-UUID form.

A native `uuid.UUID` is not JSON-serializable. `aggregate.to_dict()` therefore
carried a value that `json.dumps` rejects with `Object of type UUID is not JSON
serializable`. This error breaks each path that serializes an aggregate: event
and command payloads written to the event store and brokers, and API responses.
In an event-driven framework an identity crosses a JSON boundary constantly, so
this is a hot-path defect, not an edge case. The divergence went unnoticed
because the one test covering uuid identity wrapped the value in `str()` before
asserting. That assertion passes whether the id is a native `UUID` or a string.

## Decision

**A uuid identity is a UUID *string* in Python, on every path.**

The generator returns `str(uuid4())` for `identity_type = "uuid"`. The
auto-injected `id` field carries a narrow `UUID -> str` coercion (a
`BeforeValidator`) that leaves an `integer` identity as an `int`. Explicitly
declared `Auto`/`Identifier` fields already apply the same coercion. With it, a
native `UUID` that a caller passes or an adapter returns on load (for example
SQLAlchemy's `GUID` type) also becomes a string. Read-optimized projection
results (`QuerySet.only(...)`) bypass entity construction and its validator, so
the default record builder and the Elasticsearch identity extraction coerce
their identity as well. The contract therefore holds on read paths that never
build a full entity.

The native-UUID representation stays an **adapter and storage** concern: an
adapter that supports a native UUID column continues to store the value in one
(SQLAlchemy maps `identity_type = "uuid"` to its `GUID` type). The Python-side
domain identity is an opaque string.

## Consequences

- `to_dict()`, event and command payloads, and API responses are JSON-serializable
  under every `identity_type`.
- The auto-injected and explicitly declared identity paths produce the same
  runtime type, so identity behavior no longer depends on whether the `id` field
  was declared.
- Native UUID database columns still work, so the storage and indexing reasons
  for choosing `uuid` over `string` still hold. The two types now differ only
  in UUID-format validation and in the column type an adapter selects, and the
  Python type is the same.
- `identity_type = "uuid"` no longer yields a native `uuid.UUID` in Python. If
  your code relied on the (previously broken, non-serializable) native-UUID id,
  it must call `uuid.UUID(id)` explicitly. This is a behavior change,
  documented in the 0.17 upgrade notes.

## Alternatives Considered

**Native `uuid.UUID` in Python (make it work end to end).** Keep the id a real
`UUID` object and teach `to_dict()` and every event/command payload serializer
to stringify UUIDs at the boundary, flipping the explicit path from `str` to
`UUID` for consistency. Rejected: it adds a UUID-aware serialization step
across the event-sourcing hot path and the whole framework, changes the
established `str` behavior of explicit identifiers, and changes far more code.
Domains treat identities as opaque handles, so they rarely need the richer type
it would give. An adapter can store the identity in a native UUID column while
the aggregate or entity holds it as a string.
