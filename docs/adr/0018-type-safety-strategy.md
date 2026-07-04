# ADR-0018: Type-safety adoption strategy

**Status:** Accepted

**Date:** July 2026

## Context

Protean ships a `py.typed` marker, so downstream users rely on its annotations
for their own type-checking. But the framework's own source is **not** type-checked
in CI. A typed library that doesn't type-check itself gives users a weaker type
experience than it advertises.

The measured baseline (June 2026): **~700 mypy errors across 87 files** under the
current lenient config, and **~2,400 under `--strict`**. The only mypy in CI today
is `tests/ext/`, which checks the **plugin against fixtures**, not the source — so
none of the 700 errors are gated, and new type debt accrues freely.

Two constraints shape the approach:

- **It cannot be a big-bang.** A single 700-error (or 2,400-error) PR is
  unreviewable and would freeze feature work while it's in flight.
- **The mypy plugin types *user* code, not the framework's own source.** The
  plugin (`src/protean/ext/mypy_plugin.py`) makes `String()` resolve to `str` and
  injects base classes for decorator-registered elements in *downstream* code. The
  framework's own modules must type-check on explicit annotations, independent of
  the plugin (except where the framework consumes its own field/element machinery).

## Decision

Adopt type safety with a **quarantine-then-ratchet** strategy — the same path
large codebases (e.g. Dropbox) used to adopt mypy.

- **Gate mypy in CI now, against a per-module quarantine.** `[tool.mypy]` carries
  a `[[tool.mypy.overrides]]` list of the currently-failing modules with
  `ignore_errors = true`. A clean run is therefore green, and mypy **blocks any
  new error in a non-quarantined module**. The quarantine list is
  **append-only-shrinking**: every subsequent sub-issue strictifies its modules
  and deletes them from the list. The end state is an empty list and
  `strict = true` globally.

- **Enable strict flags by cost.** `no_implicit_optional` is already on (free);
  `warn_unused_ignores` is enabled now (cheap — it forced a one-time cleanup of
  stale `type: ignore`s). The expensive levers (`disallow_any_generics`,
  `disallow_untyped_defs`, full `--strict`) are not global switches; they fall out
  naturally per-module as each quarantine entry is cleared.

- **The plugin is independent of source strictness.** Making the framework strict
  does not require plugin changes, except where the framework consumes its own
  field/element machinery — that plugin hardening happens alongside `fields/`.

- **`py.typed` is a contract.** The public surface (`__init__.py` exports,
  `protean.fields`, `QuerySet`/DSL, `Domain` methods) gets first-class annotations
  so downstream `reveal_type` is accurate.

- **Sequence respects coupling:** `utils`/`port` → `fields` (+plugin) → `core` →
  `domain` → `adapters`/`server` → `cli`/`ir`. Each step removes its modules from
  the quarantine and ships its own tests.

## Consequences

- CI blocks new type debt **immediately**, while existing debt is an explicit,
  visible, shrinking allowlist rather than an invisible backlog.
- The migration proceeds incrementally without freezing feature work; each
  sub-issue is independently reviewable and ships tests.
- Downstream users get progressively more accurate types as the quarantine
  shrinks, backed by the `py.typed` contract.
- The quarantine is coarse: `ignore_errors = true` silences *all* errors in a
  quarantined module, so a regression inside a still-quarantined module is not
  caught until that module is strictified. This is an accepted trade for a green,
  enforceable gate today.
- Reaching `strict = true` takes several sub-issues (D2–D6); the hardest
  (`fields/`, `core/`) require plugin and pydantic-interaction work, not just
  annotations.

## Alternatives Considered

- **Big-bang `--strict`.** Rejected: a 2,400-error PR is unreviewable and would
  freeze feature work; type quality would arrive as one high-risk drop instead of
  a ratchet.
- **Leave the source untyped.** Rejected: shipping `py.typed` while not
  type-checking the source misrepresents the type quality users receive.
- **Gradual typing with no CI gate.** Rejected: without the gate there is no
  ratchet — new debt accrues as fast as old debt is paid down.
