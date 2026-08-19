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
And the change is a **contract between producers and a consumer that ship on
different schedules**: the `add` engine and versioned upgrades both emit plans,
and an applier (a later epic) executes them. A contract read by code that was
written against a different version of it has to fail loudly rather than
misread, so the shape is versioned.

The `add`/change machinery is neither IR nor CLI glue, so it gets its own package,
`protean.scaffold`, that later scaffolding work populates.

## Decision

We define a `ChangePlan`: an ordered tuple of operations plus an optional
description, homed in `protean.scaffold`.

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
  commented `domain.toml` breaks easily on the one operation `add` runs most, and
  it would contradict the tomlkit-for-config direction the program has already
  committed to.

The plan follows the existing serialization house style, matching `protean.ir`: a
frozen dataclass serialized by an explicit `to_dict`/`from_dict` JSON dump, not
pydantic (pydantic is reserved for domain elements). The serialized form carries a
`plan_version` marker, and a versioned JSON Schema lives at
`schema/v<version>/schema.json`, starting at `0.1.0`. `from_dict` rejects a
`plan_version` it does not understand, an unknown operation `kind`, and any
missing required field with a clear `ValueError`, the same way `load_config` and
`load_stored_ir` reject malformed input.

Preview is read-only and separate from an operation's representation. A
`render_preview(plan)` function builds a human-readable summary as pure strings: a
create shows a header plus its content, an edit shows its unified diff, and a
config op shows `key.path = value  (set|merge)`. The renderer opens, stats, and
creates nothing.

Applying a plan is out of scope here. This issue defines the shape and the
preview; the transactional applier is a later epic, and the `tomlkit` dependency
that writes `domain.toml` lands with the config applier, not now.

## Consequences

- A command can build one `ChangePlan`, preview it, and hand the same object to an
  applier, so show and apply stay in sync because they read one shape.
- The preview is safe to run anywhere: it is provably read-only, so it needs no
  confirmation and no rollback.
- Versioning the schema means an old build meeting a newer plan fails loudly
  instead of silently misapplying it. The cost is that `plan_version` and the
  JSON Schema must be bumped together whenever the shape changes.
- Keeping config structured means the applier works against parsed config, not
  text, so a reformatted or commented `domain.toml` cannot break a config edit.
  The cost is that config is not one uniform "diff" with file edits; a renderer
  and an applier each special-case it.
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
- **One combined "file operation" covering create and edit.** Rejected: a create
  carries whole content and an edit carries a diff; they are different shapes, and
  a discriminated union keeps each one's required fields honest.
