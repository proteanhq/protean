# ADR-0034: Derived Project Manifest (`.protean/project.json`)

**Status:** Accepted

**Date:** August 2026

## Context

`protean new` stamps a project whose shape is a contract (ADR-0030): one
composition root at `src/<package>/domain.py`, `domain.toml` beside it,
`tests/` a sibling of `src/`. Three tools later in this epic need a project's
package name, its domain name, and those layout paths: the additive `add`
engine, the renderer, and the drift checks. Each tool needs these values
without re-guessing them from the template each time.

The pieces are already on disk. The package and the domain name both come from
`domain.py`: the package is the `src/` directory that holds it, and the domain
name is the `name=` of the `Domain(...)` call in that file. The project-shape
contract (ADR-0030) fixes the layout. Tooling could recompute all of it every
time. A committed manifest records the answer in one file, next to
`.protean/ir.json` and `.protean/config.toml`. A person or a tool can then read
the project's shape without importing and initialising the domain.

Any persisted record of derived facts can drift from the code. A developer or a
tool may then trust the stale copy. This ADR fixes the contract that keeps that
from happening.

## Decision

The manifest is stored at `.protean/project.json`, in the same directory as
`ir.json` and `config.toml`. `protean new` copies the template and then calls
`protean.scaffold.manifest.write_manifest`, which writes the manifest. The
manifest writer is the first step to create `.protean/`. The writer leaves a
pre-existing `config.toml` or `ir.json` unchanged. `--dry-run` writes nothing.

**Contract: derived, verifiable, never authoritative.** Every field is
recomputed from its own source on disk. No tool reads the stored file to
override the code. Because of this rule, you can commit the manifest safely.
The manifest can go stale, but it can never mislead, because no tool treats it
as the source of truth.

**Each field comes from one source on disk:**

- `manifest_version`: the schema version of the JSON shape (`"1.0"`).
- `package_name`: the single `src/*/` directory that contains `domain.py`. Exactly
  one is expected. Zero or more than one is an error, because a project has
  exactly one composition root under the project-shape contract (ADR-0030).
- `domain_name`: the string-literal `name=` of the module-level `Domain(...)`
  assignment in that `domain.py`, parsed with `ast`. Only module-level
  assignments count, because under the project-shape contract (ADR-0030) the
  composition root is a module-level assignment. A `Domain(...)` call inside a
  function or class body is not the composition root. It is `null` when the
  name is not a string literal (for example a variable) or when there is no
  such assignment, so an unusual composition root degrades to "underivable"
  instead of crashing.
- `layout`: the layout invariants of the project-shape contract (ADR-0030),
  stored relative to the project root and POSIX-normalised so the JSON is the
  same on every operating system. It holds `composition_root`
  (`src/<package>/domain.py`), `config_file` (`src/<package>/domain.toml`), and
  `tests_dir` (`tests`).

**How the drift check works.** `check_manifest_drift(project_root)` loads the
stored manifest, recomputes the manifest from disk, and compares field by
field. It returns `MATCH`, `DRIFTED` with a per-field list of `(field, stored,
recomputed)` divergences, or `NO_MANIFEST` when no file exists. It mutates
nothing. The check reports a hand-edited manifest that disagrees with the code
as drift. It always recomputes the value from disk and treats that value as
authoritative.

## Consequences

Tooling reads a project's package, domain name, and layout from one committed file
instead of re-deriving them or importing the domain. The drift check gives a person a
way to confirm the committed manifest still matches the code.

The manifest is not a source of truth and must never become one. Any consumer
that needs a field recomputes it (or calls `reconcile_manifest`) rather than
trusting the stored value. A future consumer that honours the stored file over
disk breaks the derived, never-authoritative contract. That consumer brings
back the stale-copy hazard the contract exists to prevent.

The persisted shape is versioned by `manifest_version`. A Protean maintainer
bumps `manifest_version` whenever the fields or their JSON layout change. A
reader can then tell an old manifest from a current one.

## Alternatives Considered

**Store the manifest as authoritative and let tooling trust it.** Protean
rejects this option because it breaks the derived, never-authoritative
contract. Suppose tooling honours a committed record over the code. When a
developer renames a package or edits `domain.py`, the record goes stale and
every consumer reads the same wrong value. When each tool recomputes from disk,
the code stays the single source of truth and the manifest is only a
convenience.

**Recompute everything on every read and persist nothing.** Correct, but it
means any tool that wants the project's shape has to import and initialise the
domain, or re-parse the tree, each time. The committed file lets a person or a
tool read the shape cheaply. The drift check catches a committed file that has
gone stale.

**Put the manifest under `src/protean/ir/`.** The manifest code reuses the
shapes of `ir/staleness.py` (a frozen result, a status enum, a mutation-free
check, a `load_stored_*` helper) but none of its code. The manifest describes
project layout and has nothing to do with the IR. Protean puts the
project-shape code in a separate `src/protean/scaffold/` package, outside the
IR package. The rest of this epic adds its code to the same package.
