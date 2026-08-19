# ADR-0034: Derived Project Manifest (`.protean/project.json`)

**Status:** Accepted

**Date:** August 2026

## Context

`protean new` stamps a project whose shape is a contract (ADR-0030): one composition
root at `src/<package>/domain.py`, `domain.toml` beside it, `tests/` a sibling of
`src/`. Later tooling in this epic (the additive `add` engine, the renderer, drift
checks) needs to know a project's package name, its domain name, and those layout
paths without re-guessing them from the template each time.

The pieces are already on disk. The package is the `src/` directory that holds
`domain.py`, the domain name is the `name=` of the `Domain(...)` call in that file,
and the layout is fixed by ADR-0030. Tooling could recompute all of it every time.
A committed manifest records the answer in one place, next to `.protean/ir.json` and
`.protean/config.toml`, so a person or a tool can read the project's shape without
importing and initialising the domain.

The risk with any persisted record of derived facts is that it drifts from the code
and someone starts trusting the stale copy. This ADR fixes the contract that keeps
that from happening.

## Decision

The manifest lives at `.protean/project.json`, a sibling of `ir.json` and
`config.toml`. It is written by `protean.scaffold.manifest.write_manifest`, which
`protean new` calls after the template is copied. The manifest writer is the first
thing to create `.protean/`, and it does not touch a pre-existing `config.toml` or
`ir.json`. `--pretend` writes nothing.

**Contract: derived, verifiable, never authoritative.** Every field is recomputed
from its own source on disk. The stored file is never read to override the code. This
is the rule that makes the manifest safe to commit: it can go stale, but it can never
mislead, because nothing consults it as truth.

**Fields and their sources:**

- `manifest_version`: the schema version of the JSON shape (`"1.0"`).
- `package_name`: the single `src/*/` directory that contains `domain.py`. Exactly
  one is expected. Zero or more than one is an error, since ADR-0030 fixes one
  composition root per project.
- `domain_name`: the string-literal `name=` of the module-level `Domain(...)`
  assignment in that `domain.py`, parsed with `ast`. Only module-level assignments
  count, since ADR-0030 puts the composition root at module level; a `Domain(...)`
  call inside a function or class body is not it. It is `null` when the name is not
  a string literal (for example a variable) or when there is no such assignment, so
  an unusual composition root degrades to "underivable" instead of crashing.
- `layout`: the ADR-0030 invariants, stored project-root-relative and
  POSIX-normalised so the JSON is stable across operating systems. It holds
  `composition_root` (`src/<package>/domain.py`), `config_file`
  (`src/<package>/domain.toml`), and `tests_dir` (`tests`).

**Drift check.** `check_manifest_drift(project_root)` loads the stored manifest,
recomputes the manifest from disk, and compares field by field. It returns `MATCH`,
`DRIFTED` with a per-field list of `(field, stored, recomputed)` divergences, or
`NO_MANIFEST` when no file exists. It mutates nothing. Because the recomputed value
always comes from disk, a hand-edited manifest that disagrees with the code is
reported as drift, and the code's value is what the check reports as authoritative.

## Consequences

Tooling reads a project's package, domain name, and layout from one committed file
instead of re-deriving them or importing the domain. The drift check gives a person a
way to confirm the committed manifest still matches the code.

The manifest is not a source of truth and must never become one. Any consumer that
needs a field recomputes it (or calls `reconcile_manifest`) rather than trusting the
stored value. If a future consumer starts honouring the stored file over disk, it
breaks this contract and brings back exactly the stale-copy hazard the derived rule
exists to prevent.

The persisted shape is versioned by `manifest_version`. A change to the fields or
their JSON layout bumps it, so a reader can tell an old manifest from a current one.

## Alternatives Considered

**Store the manifest as authoritative and let tooling trust it.** This is what the
derived rule rejects. A committed record that tooling honours over the code goes stale
the moment someone renames a package or edits `domain.py`, and then every consumer is
wrong in the same direction. Recomputing from disk keeps the code as the single source
of truth and reduces the manifest to a convenience.

**Recompute everything on every read and persist nothing.** Correct, but it means any
tool that wants the project's shape has to import and initialise the domain, or
re-parse the tree, each time. The committed file lets a person or a tool read the
shape cheaply, and the drift check covers the staleness risk that persistence
introduces.

**Put the manifest under `src/protean/ir/`.** The manifest reuses the shapes of
`ir/staleness.py` (a frozen result, a status enum, a mutation-free check, a
`load_stored_*` helper) but none of its code, and it reasons about project layout, not
the IR. A separate `src/protean/scaffold/` package keeps the project-shape concern out
of the IR package, and the rest of this epic grows into the same package.
