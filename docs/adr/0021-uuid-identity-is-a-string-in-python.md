# ADR-0021: A uuid identity is a string in Python

**Status:** Accepted

**Date:** July 2026

## Context

Protean's identity system supports three identity types, selected by
`identity_type` in configuration: `string`, `integer`, and `uuid`. The value is
produced by a single generator and injected as the aggregate's (or entity's)
`id` field when no identifier is declared explicitly.

Historically the two identity paths disagreed under `identity_type = "uuid"`. The
**auto-injected** `id` field held a native `uuid.UUID` object, while an
**explicitly declared** `Auto(identifier=True, identity_type="uuid")` field
coerced its value to a `str`. The auto-injected path is the default, so most code
hit the native-UUID form.

A native `uuid.UUID` is not JSON-serializable. `aggregate.to_dict()` therefore
carried a value that `json.dumps` rejects with `Object of type UUID is not JSON
serializable`, which breaks the paths that serialize an aggregate: event and
command payloads written to the event store and brokers, and API responses. In an
event-driven framework an identity crosses a JSON boundary constantly, so this is
a hot-path defect, not an edge case. The divergence had gone unnoticed because the
one test covering uuid identity wrapped the value in `str()` before asserting,
which passes whether the id is a native `UUID` or a string.

## Decision

**A uuid identity is a UUID *string* in Python, on every path.**

The generator returns `str(uuid4())` for `identity_type = "uuid"`, and the
auto-injected `id` field carries a narrow `UUID -> str` coercion (a
`BeforeValidator`) that leaves an `integer` identity as an `int`. This mirrors the
coercion that explicitly declared `Auto`/`Identifier` fields already apply, so a
value that reaches the field as a native `UUID`, whether passed by a caller or
returned by an adapter on load (for example SQLAlchemy's `GUID` type), becomes a
string too. Read-optimized projection results (`QuerySet.only(...)`, which bypass
entity construction and its validator) coerce the identity as well, in the default
record builder and in the Elasticsearch identity extraction, so the contract holds
on read paths that never build a full entity.

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
- Native UUID database columns still work, so the storage/indexing rationale for
  choosing `uuid` over `string` is preserved: the difference is UUID-format
  validation and the column type an adapter selects, not the Python type.
- `identity_type = "uuid"` no longer yields a native `uuid.UUID` in Python. Code
  that relied on the (previously broken, non-serializable) native-UUID id must
  call `uuid.UUID(id)` explicitly. This is a behavior change, documented in the
  0.17 upgrade notes.

## Alternatives Considered

**Native `uuid.UUID` in Python (make it work end to end).** Keep the id a real
`UUID` object and teach `to_dict()` and every event/command payload serializer to
stringify UUIDs at the boundary, flipping the explicit path from `str` to `UUID`
for consistency. Rejected: it imposes a UUID-aware serialization step across the
event-sourcing hot path and the whole framework, changes the established `str`
behavior of explicit identifiers, and carries a far larger blast radius, all for a
type-richness benefit that domains (which treat identities as opaque handles)
rarely need. Storing a native UUID column is achievable without holding a native
UUID in the domain object.
