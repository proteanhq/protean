# ADR-0026: Sanitized String Values Satisfy Their Field's Length Bounds

**Status:** Accepted

**Date:** July 2026

## Context

`String` and `Text` fields sanitize their input by default (`sanitize=True`),
running `bleach.clean()`. Sanitization changes the length of the value in both
directions: it *lengthens* by HTML-escaping (`&` → `&amp;`, `<` → `&lt;`,
`>` → `&gt;` — one character becomes up to five), and it *shortens* by stripping
HTML comments and disallowed attributes.

`min_length` and `max_length` are Pydantic core constraints, so they run on the
*raw* input before sanitization. The value that actually gets stored is the
*sanitized* one. Those two forms diverge whenever sanitization changes the
length, and the consequence is a broken round-trip:

- `String(max_length=50)` given `"&" * 11` passes the length check (11 ≤ 50) and
  stores `"&amp;" * 11` — a 55-character value.
- `String(min_length=8)` given `"hi<!-- a long comment -->"` passes (25 ≥ 8) and
  stores `"hi"` — a 2-character value.
- A **required** `String` (implicit `min_length=1`) given `"<!--x-->"` passes and
  stores `""`.

Re-validating any of those stored values against the same field — on a
serialization round-trip, or when an event-sourced aggregate replays its stream —
fails. For an event-sourced aggregate this is a silent-corruption path: the event
is accepted and committed, but the aggregate can no longer be reconstituted from
its stream. A committed event you cannot replay is data loss.

A related failure affects `choices`. A `String(choices=[...])` compiles the
choices into a `Literal` core constraint checked on the raw input, but
sanitization then mutates the stored value so it no longer matches any choice —
so the object holds an invalid value immediately, and replay fails. (`Status`
fields are not affected: they default to `sanitize=False`.)

`bleach.clean` is idempotent (`clean(clean(x)) == clean(x)`; it recognizes
existing entities and does not re-escape `&amp;`, and re-stripping an
already-stripped string is a no-op), so there is no double-transform corruption —
the stored value is stable. The only defect is that the field accepts values it
will not later re-accept.

The bug was found by the property-based verification suite added in #1252
(epic #1199): a replay-determinism property generated a name with `<`/`&` near
the length boundary and `from_events` raised.

## Decision

**The sanitized (stored) value must satisfy its field's length bounds and choice
set, so a value accepted on write always round-trips.** Two changes:

1. **Length bounds are re-checked on the sanitized value.** The sanitization
   `AfterValidator` on `String`/`Text` fields now also enforces `min_length` and
   `max_length` (including a required field's implicit `min_length` of 1) on its
   output. A value whose sanitized form falls outside the bounds is rejected at
   write time with a clear message (`"String has N characters after sanitization,
   exceeding max_length of M"` / `"... below min_length of M"`) rather than being
   stored in a form the field rejects on the way back. The core constraints still
   run first on the raw input (so plain out-of-bounds input keeps its standard
   error) and still drive the JSON Schema and database column length.

2. **`choices` fields are not sanitized.** When `choices` is set, sanitization is
   skipped entirely: the value must match a declared choice exactly, the choice
   set is a closed developer-defined vocabulary, and HTML-escaping it would break
   the match. The stored value is the raw choice, which round-trips.

Fields with `sanitize=False` are unaffected: their stored value equals their raw
input, so the bounds already apply to what is stored.

## Consequences

- **Round-trip and replay hold for accepted values.** A value a field accepts
  can be serialized, stored, and replayed without a length or choice error. No
  committed event can be unreplayable because sanitization moved the stored value
  out of bounds.
- **Some writes that previously succeeded now fail.** Input whose sanitized form
  falls outside the length bounds is rejected instead of silently stored. These
  are precisely the values that produced unreplayable data. The remedy is to
  widen the bound or set `sanitize=False`.
- **A value is accepted only if both its raw and sanitized forms satisfy the
  bounds.** The core constraint still checks the raw input, and the new check
  covers the sanitized form, so acceptance is the intersection. Because escaping
  only grows the value and stripping only shrinks it, this can over-reject at the
  edges — e.g. a raw input just over `max_length` whose stripped form would fit is
  still rejected on its raw length. This is fail-safe (rejection, never
  corruption) and is documented behavior, not a claim that the bound applies to
  the stored value alone.
- **`choices` fields change behavior.** A sanitized `choices` field previously
  stored an escaped value that no longer matched its own choice list (a latent
  bug); it now stores the raw choice. Escapable characters in a choice value are
  no longer HTML-escaped — acceptable because the vocabulary is developer-defined,
  not free user input.
- **Existing streams already holding an out-of-bounds value are not healed.** This
  change prevents new unreplayable data; it does not retroactively fix a stream
  that already contains one. Those values must be migrated (widen the bound, or
  re-key with `sanitize=False`). In practice this population is expected to be
  empty: the default `max_length` is 255 and it takes escapable characters near
  the limit to overflow.
- **The guarantee rests on `bleach` idempotency.** On replay the stored value is
  sanitized again; only because `clean(stored) == stored` does its length stay in
  bounds. A future non-idempotent sanitizer or config would reopen the round-trip
  hole; the fix checks length against a single sanitize pass.

## Alternatives Considered

- **Fix only `max_length` (the originally reported symptom).** Rejected: the same
  raw-vs-stored divergence breaks `min_length`, a required field's implicit
  minimum, and `choices` — all the same silent-corruption / unreplayable class.
  Fixing one manifestation and leaving the others is not a real fix.
- **Trusted deserialization: skip re-validation when rehydrating stored data.**
  Treat validation and sanitization as boundary concerns for fresh input only,
  and bypass them when reconstituting trusted stored data. This heals existing
  streams and changes no write behavior, and is conceptually clean ("do not treat
  your own store as an attacker"). Rejected as too large and risky: it means
  threading a "trusted" path through the deserialization choke point, which also
  carries lenient-mode, alias, and coercion logic, and disabling re-validation
  there weakens a genuine guard.
- **Run sanitization as a `BeforeValidator` so the core constraints see the
  stored value.** This would collapse the length bounds to a single source of
  truth (no re-check). Rejected: a `BeforeValidator` runs before type coercion, so
  it would sanitize the raw input before it is a string — a `bytes` value would
  be decoded to `str` by the core *after* sanitization and never get sanitized,
  a security regression. Keeping sanitization post-coercion and re-checking the
  bounds avoids that hole. It also forfeits the diagnostic error message (the
  generic "at most N characters", confusing for an input that was well under the
  limit before escaping).
- **Measure the pre-escape (semantic) length on read.** Not reliably
  implementable: sanitization is not reversible (`&amp;` could be an escaped `&`
  or a literal `&amp;`; a stripped comment cannot be recovered), so the original
  length cannot be reconstructed from the stored value.
