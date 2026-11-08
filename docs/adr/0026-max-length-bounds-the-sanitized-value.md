# ADR-0026: Sanitized String Values Satisfy Their Field's Length Bounds

**Status:** Accepted

**Date:** July 2026

> **What changed in 0.18.0:** the framework `sanitize` default flipped from
`True` to `False` (issue #1455). This ADR still holds wherever a field does
sanitize > (an explicit `sanitize=True`, or an unset field under a domain
> `[field_defaults] sanitize = true`): the length re-check runs on that path.
> The sentence below describing the default is historical.

## Context

`String` and `Text` fields sanitize their input by default (`sanitize=True`),
running `bleach.clean()`. Sanitization changes the length of the value in both
directions. HTML-escaping *lengthens* it (`&` → `&amp;`, `<` → `&lt;`, `>` →
`&gt;`; one character becomes up to five), and stripping HTML comments and
disallowed attributes *shortens* it.

`min_length` and `max_length` are Pydantic core constraints, so they run on the
*raw* input before sanitization. The value that actually gets stored is the
*sanitized* one. Those two forms diverge whenever sanitization changes the
length, and the consequence is a broken round-trip:

- `String(max_length=50)` given `"&" * 11` passes the length check (11 ≤ 50) and
  stores `"&amp;" * 11`, a 55-character value.
- `String(min_length=8)` given `"hi<!-- a long comment -->"` passes (25 ≥ 8) and
  stores `"hi"`, a 2-character value.
- A **required** `String` (implicit `min_length=1`) given `"<!--x-->"` passes and
  stores `""`.

Each of those stored values fails re-validation against the same field, whether
on a serialization round-trip or when an event-sourced aggregate replays its
stream. For an event-sourced aggregate this is a silent-corruption path: the
event is accepted and committed, but the aggregate can no longer be
reconstituted from its stream. A committed event you cannot replay is data
loss.

A related failure affects `choices`. A `String(choices=[...])` compiles the
choices into a `Literal` core constraint that checks the raw input.
Sanitization then mutates the stored value so it no longer matches any choice.
The object holds an invalid value immediately, and replay fails. (`Status`
fields are not affected: they default to `sanitize=False`.)

`bleach.clean` is idempotent (`clean(clean(x)) == clean(x)`), so there is no
double-transform corruption. It recognizes existing entities and does not
re-escape `&amp;`, and re-stripping an already-stripped string is a no-op. The
stored value is stable. The only defect is that the field accepts values it
will not later re-accept.

The bug was found by the property-based verification suite added in #1252
(epic #1199): a replay-determinism property generated a name with `<`/`&` near
the length boundary and `from_events` raised.

## Decision

**The sanitized (stored) value must satisfy its field's length bounds and choice
set, so a value accepted on write always round-trips.** Two changes:

1. **Length bounds are re-checked on the sanitized value**: The sanitization
   `AfterValidator` on `String`/`Text` fields now also enforces `min_length` and
   `max_length` (including a required field's implicit `min_length` of 1) on its
   output. The `AfterValidator` rejects a value at write time when its
   sanitized form falls outside the bounds, with a clear message
   (`"String has N characters after sanitization, exceeding max_length of M"` /
   `"... below min_length of M"`). So the field never stores a value that it
   rejects on re-validation. The core constraints still run first on the raw
   input (so plain out-of-bounds input keeps its standard
   error) and still drive the JSON Schema and database column length.

2. **`choices` fields are not sanitized**: When `choices` is set, the field
   skips sanitization entirely, because the value must match a declared choice
   exactly. The choice set is a closed developer-defined vocabulary, and
   HTML-escaping a choice would break the match. The stored value is the raw
   choice, which round-trips.

Fields with `sanitize=False` are unaffected: their stored value equals their raw
input, so the bounds already apply to what is stored.

## Consequences

- **Round-trip and replay hold for accepted values**: A value a field accepts
  can be serialized, stored, and replayed without a length or choice error.
  Sanitization can no longer move a stored value out of bounds, so no event
  committed after this change is unreplayable for that reason.
- **Some writes that previously succeeded now fail**: Input whose sanitized form
  falls outside the length bounds is rejected instead of silently stored. These
  are precisely the values that produced unreplayable data. The remedy is to
  widen the bound or set `sanitize=False`.
- **A value is accepted only if both its raw and sanitized forms satisfy the
  bounds.** The core constraint still checks the raw input, and the new check
  covers the sanitized form, so acceptance is the intersection. Escaping only
  grows the value and stripping only shrinks it, so the two checks can
  over-reject values near the bounds. For example, the core constraint still
  rejects a raw input just over `max_length` on its raw length, even when its
  stripped form would fit. This over-rejection is fail-safe: it rejects input
  and never corrupts stored data. It is documented behavior, and the bound
  applies to both the raw value and the stored value.
- **`choices` fields change behavior**: A sanitized `choices` field previously
  stored an escaped value that no longer matched its own choice list (a latent
  bug); it now stores the raw choice. Escapable characters in a choice value are
  no longer HTML-escaped. Acceptable because the vocabulary is
  developer-defined, not free user input.
- **Existing streams already holding an out-of-bounds value are not healed**: This
  change prevents new unreplayable data; it does not retroactively fix a stream
  that already contains one. Those values must be migrated (widen the bound, or
  re-key with `sanitize=False`). In practice no stream is expected to hold such
  a value: the default `max_length` is 255 characters, and a value overflows
  only when it has escapable characters near that limit.
- **The guarantee rests on `bleach` idempotency**: On replay the field
  sanitizes the stored value again. Its length stays in bounds only because
  `clean(stored) == stored`. A future non-idempotent sanitizer or config would
  make round-trips fail again, because the fix checks length against a single
  sanitize pass.

## Alternatives Considered

- **Fix only `max_length` (the originally reported symptom)**: Rejected: the same
  raw-vs-stored divergence breaks `min_length`, a required field's implicit
  minimum, and `choices`, all the same silent-corruption / unreplayable class. Fixing
  one manifestation and leaving the others is not a real fix.
- **Trusted deserialization: skip re-validation when rehydrating stored data.**
  Treat validation and sanitization as boundary concerns for fresh input only,
  and bypass them when reconstituting trusted stored data. This approach would
  fix existing streams and change no write behavior. It is also conceptually
  clean ("do not treat your own store as an attacker"). Rejected as too large
  and risky: it means adding a "trusted" code path to the shared
  deserialization step, which also runs lenient-mode, alias, and coercion
  logic. Disabling re-validation in that step would weaken a genuine guard.
- **Run sanitization as a `BeforeValidator` so the core constraints see the
  stored value.** The core constraints would then be the only length check.
  Rejected: a `BeforeValidator` runs before type coercion, so it would sanitize
  the raw input before it is a string. A `bytes` value would
  be decoded to `str` by the core *after* sanitization and never get sanitized,
  a security regression. The chosen design runs sanitization after coercion and
  re-checks the bounds, so a `bytes` value is still sanitized. The
  `BeforeValidator` option would also lose the diagnostic error message and
  show the generic "at most N characters", which is confusing for an input that
  was well under the limit before escaping.
- **Measure the pre-escape (semantic) length on read**: Not reliably
  implementable, because sanitization is not reversible, so the original length
  cannot be reconstructed from the stored value. `&amp;` could be an escaped
  `&` or a literal `&amp;`, and a stripped comment cannot be recovered.
