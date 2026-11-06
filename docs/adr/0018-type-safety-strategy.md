# ADR-0018: Type-safety adoption strategy

**Status:** Accepted

**Date:** July 2026

## Context

Protean ships a `py.typed` marker, so downstream users rely on its annotations
for their own type-checking. But the framework's own source is **not**
type-checked in CI. When a typed library does not type-check its own source,
users get weaker types than the library advertises.

The measured baseline (June 2026): **~700 mypy errors across 87 files** under
the current lenient config, and **~2,400 under `--strict`**. Today CI runs mypy
only on `tests/ext/`, and that run checks the **plugin against fixtures** and
skips the source. As a result, CI gates none of the 700 errors, and nothing
blocks new type debt.

Two constraints shape the approach:

- **The work cannot ship as one PR**: A single 700-error (or 2,400-error) PR is
  unreviewable. It would also block feature work for as long as it stays open.
- **The mypy plugin types *user* code, not the framework's own source.** The
  plugin (`src/protean/ext/mypy_plugin.py`) makes `String()` resolve to `str` and
  injects base classes for decorator-registered elements in *downstream* code. The
  framework's own modules must type-check on explicit annotations, independent of
  the plugin (except where the framework consumes its own field/element machinery).

## Decision

Adopt type safety with a **quarantine-then-ratchet** strategy: mypy skips a
fixed list of failing modules, and each later change removes modules from that
list and never adds one. Large codebases (e.g. Dropbox) adopted mypy the same
way.

- **Gate mypy in CI now, against a per-module quarantine**: `[tool.mypy]` carries
  a `[[tool.mypy.overrides]]` list of the currently-failing modules with
  `ignore_errors = true`. A clean run therefore passes. From then on, mypy
  **blocks any new error in a non-quarantined module**. The quarantine list
  **only shrinks**: every later sub-issue makes its modules pass strict checks
  and deletes them from the list. The end state is an empty list and `strict =
  true` globally.

- **Enable strict flags by cost**: `no_implicit_optional` is already on and
  costs nothing. `warn_unused_ignores` is enabled now at low cost, and enabling
  it forced a one-time cleanup of stale `type: ignore`s. The expensive flags
  (`disallow_any_generics`, `disallow_untyped_defs`, full `--strict`) stay off
  globally. Each module passes them once a contributor clears its quarantine
  entry.

- **The plugin is independent of source strictness**: Making the framework strict
  does not require plugin changes, except where the framework consumes its own
  field/element machinery. Contributors harden the plugin in the same step that
  makes `fields/` strict.

- **`py.typed` is a contract**: The public surface (`__init__.py` exports,
  `protean.fields`, `QuerySet`/DSL, `Domain` methods) gets complete, precise
  annotations so downstream `reveal_type` is accurate.

- **Order the steps by module coupling:** `utils`/`port` → `fields` (+plugin) →
  `core` → `domain` → `adapters`/`server` → `cli`/`ir`. In each step of this
  order, a contributor removes that step's modules from the quarantine. The
  same change ships its own tests.

## Consequences

- CI blocks new type debt **immediately**, while existing debt is an explicit,
  visible, shrinking allowlist rather than an invisible backlog.
- The migration proceeds in small steps, and feature work continues during it.
  Each sub-issue can be reviewed on its own and ships tests.
- Downstream users get progressively more accurate types as the quarantine
  shrinks, backed by the `py.typed` contract.
- The quarantine is coarse: `ignore_errors = true` silences *all* errors in a
  quarantined module. mypy therefore misses a regression inside a
  still-quarantined module until a contributor makes that module strict. This
  is an accepted trade for a green, enforceable gate today.
- Reaching `strict = true` takes several sub-issues (D2–D6). The hardest ones
  (`fields/`, `core/`) need plugin work and pydantic-interaction work in
  addition to annotations.

## Alternatives Considered

- **Turn on `--strict` in one PR**: Rejected: a 2,400-error PR is unreviewable
  and would block feature work. Type quality would arrive in one high-risk
  change, without the step-by-step tightening the quarantine gives.
- **Leave the source untyped**: Rejected: if Protean ships `py.typed` and does
  not type-check its source, it misrepresents the type quality users receive.
- **Gradual typing with no CI gate**: Rejected: without the gate, nothing stops
  the error count from rising, and new type errors appear as fast as
  contributors fix old ones.
