# ADR-0005: IR-First Schema Generation

**Status:** Accepted

**Date:** March 2026

## Context

Protean needs to generate JSON Schemas for all data-carrying domain elements
(aggregates, entities, value objects, commands, events, projections).  Two
implementation strategies were considered:

1. **Pydantic-first** — call `model_json_schema()` on each domain element's
   underlying Pydantic model and post-process the output.
2. **IR-first** — build JSON Schema from the IR field metadata that the
   `IRBuilder` already extracts.

The Pydantic-first approach has a fundamental limitation: Pydantic marks
association descriptors (`ValueObject`, `HasOne`, `HasMany`, `Reference`) as
`ignored_types`, so `model_json_schema()` omits them entirely.  These
associations are the most important structural information in a domain model —
they encode aggregate cluster topology, entity ownership, and value object
embedding.

Additionally, the CLI needs to support two input modes:

- `--domain=<path>` — load a live domain, build IR, generate schemas
- `--ir=<path>` — load a previously serialized IR JSON file, generate schemas

The Pydantic-first approach only works with live domain objects.  The IR-first
approach works identically for both input modes because it operates on the same
data structure regardless of origin.

## Decision

We will build JSON Schema from the IR field metadata produced by `IRBuilder`,
not from Pydantic's `model_json_schema()`.

The generator (`protean.ir.generators.schema`) is a set of pure functions that
map IR field dicts to JSON Schema property dicts.  It handles:

- IR field kind → JSON Schema type mapping (string, integer, number, boolean,
  date, date-time, array, object)
- Constraint mapping (maxLength, minLength, minimum, maximum, enum)
- `$defs` / `$ref` resolution for nested value objects and entities
- `anyOf` wrapping for optional fields (Pydantic convention)
- `x-protean-*` extension metadata for domain-specific information
- Deterministic output (sorted keys) for diffability

A single code path (`generate_schemas(ir)`) processes both `--domain` and
`--ir` inputs, eliminating the need for separate generation logic per input
mode.

## Consequences

**Positive:**

- Complete domain topology — associations (VO, HasOne, HasMany, Reference) are
  fully represented in the schema output.
- Single code path for both `--domain` and `--ir` CLI modes.
- Pure functions with no side effects — easy to test and compose.
- No dependency on Pydantic internals or `model_json_schema()` behavior.
- IR provides a stable, versioned contract that insulates the generator from
  changes in field implementation details.

**Negative:**

- The generator must be updated when new IR field kinds are introduced.
- Any mapping bugs require manual correction rather than relying on Pydantic's
  built-in JSON Schema support.
- Pydantic-specific features (custom validators, computed fields) are not
  automatically reflected in the generated schema — they must be explicitly
  represented in the IR first.

## Alternatives Considered

**Pydantic's `model_json_schema()`** — rejected because it excludes association
descriptors (`ignored_types`), only works with live Pydantic models (not
serialized IR), and would require reimplementing descriptor semantics to patch
the output.

**Hybrid approach** (use Pydantic for standard fields, custom logic for
associations) — rejected because it introduces two code paths and makes it
harder to ensure consistency.  The IR already contains all the information
needed, so a single IR-based approach is simpler and more maintainable.
