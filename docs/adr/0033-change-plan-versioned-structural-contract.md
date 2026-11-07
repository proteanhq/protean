# ADR-0033: ChangePlan is a Versioned Structural Contract

**Status:** Accepted

**Date:** August 2026

## Context

Commands that change a project on the user's behalf (a deterministic `add`, a
versioned upgrade) need a shape for "a proposed change." Without it, a command
cannot show what it would do, ask for confirmation, and then apply the same thing
it showed. The change has to be data first: something you can build, print, diff,
store, and only later execute.

Two properties matter. The change must be **inert until applied**: producing it
touches no files, so a preview is safe to run and a plan is safe to pass around.
The change is also a **contract between producers and a consumer that ship on
different schedules**. The `add` engine and versioned upgrades both emit plans,
and an applier (a later epic) executes them. Code written against one version
of the contract may read a plan written to another version. That code has to
fail loudly instead of misreading the plan, so the plan's shape carries a
version.

The `add`/change code is part of neither the IR nor the CLI, so it gets its own
package, `protean.scaffold`. Later scaffolding work adds its code to that
package.

## Decision

We define a `ChangePlan` in `protean.scaffold`: an ordered tuple of operations
plus an optional description.

The operation set is a discriminated union tagged by a `kind` field, with three
variants:

- **create** (`kind="create"`) carries a `path` and the whole file `content`.
- **edit** (`kind="edit"`) carries a `path` and a `diff`, a unified-diff string.
  Unified diff is reviewable and standard; a structural (LibCST) applier can come
  with the patch engine later without changing this shape.
- **config** (`kind="config"`) is a **structured** key-path set/merge over
  `domain.toml`: an ordered `key_path` (e.g. `("databases", "default",
  "provider")`), a `value`, and an `operation` of `"set"` or `"merge"`. Config is
  structured data, not a text diff. A line-context diff over a reformatted,
  commented `domain.toml` breaks easily, and config edits are the operation
  `add` runs most. A text diff would also contradict the program's earlier
  decision to edit config with tomlkit.

The plan uses the same serialization style as `protean.ir`: a frozen dataclass
serialized by an explicit `to_dict`/`from_dict` JSON dump. Protean keeps
pydantic for domain elements, so the plan does not use it. The serialized form
carries a `plan_version` marker. A versioned JSON Schema is stored at
`schema/v<version>/schema.json`, and its first version is `0.1.0`. The schema
pins `plan_version` to its own version with `const`, so validating a plan
against the wrong schema fails there too, not just in `from_dict`. `from_dict`
raises a clear `ValueError` for a `plan_version` it does not understand, a
non-object entry in `operations`, an unknown operation `kind`, or any missing
or wrongly-typed required field. `load_config` and `load_stored_ir` reject
malformed input the same way. `to_json` sorts its keys, so the same plan always
serializes to the same bytes and previews and stored plans diff
cleanly.

Preview is read-only and separate from an operation's representation. A
`render_preview(plan)` function builds a human-readable summary as pure strings: a
create shows a header plus its content, an edit shows its unified diff, and a
config op shows `key.path = value  (set|merge)`. The renderer opens, stats, and
creates nothing.

Applying a plan is out of scope here. This issue defines the shape and the
preview. The transactional applier is a later epic, and the `tomlkit`
dependency that writes `domain.toml` is added later, with the config applier.

## Consequences

- A command can build one `ChangePlan`, preview it, and pass the same object to
  an applier. Show and apply read one shape, so they stay in sync.
- The preview is safe to run anywhere: it is provably read-only, so it needs no
  confirmation and no rollback.
- Versioning the schema means an old build meeting a newer plan fails loudly
  instead of silently misapplying it. The cost is that `PLAN_VERSION`, the schema
  directory name, and the schema's `plan_version` const must all be bumped
  together whenever the shape changes.
- Config stays structured, so the applier edits parsed config instead of text.
  A reformatted or commented `domain.toml` therefore cannot break a config
  edit. The cost is that config is not one uniform "diff" with file edits; a
  renderer and an applier each special-case it.
- Deferring the applier leaves a shape with no executor in this epic. That is
  deliberate: the contract is designed alongside its first consumer (the `add`
  engine) rather than in isolation.

## Alternatives Considered

- **A text diff for config.** Rejected: a line-context diff over a reformatted,
  commented `domain.toml` is fragile, and it contradicts the committed
  tomlkit-for-config direction. Config stays structured.
- **pydantic models for the plan.** Rejected for consistency: the IR
  serialization house style is frozen dataclasses with an explicit JSON dump.
  pydantic is reserved for domain elements.
- **One combined "file operation" covering create and edit.** Rejected: a
  create carries whole content and an edit carries a diff, so they are
  different shapes. A discriminated union lets each shape require its own
  fields.
