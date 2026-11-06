# Split generated wiring from hand-owned logic with a generation-gap seam (ADR-0035)

**Status:** Accepted

**Date:** August 2026

## Context

`protean add <element> <name>` plans a new element slice for an existing
project. The first version plans an aggregate slice: the aggregate, its create
command, its created event, and the command handler that connects them.
ADR-0030 defines the canonical layout `add` writes into, and ADR-0033 defines
the `ChangePlan` that `add` produces.

`add` is meant to be re-run. When a template improves, a field is added, or the
generator gains a new default, the developer runs `add` again for the same
element to get the refreshed wiring. A re-run is safe only under one condition.
Regeneration must not destroy any code the developer has written since the last
run. If generated wiring and hand-written logic share a file, a re-run has to
either overwrite the developer's edits or merge them. Both options made a
generation of model-driven tools fail. Each such tool either overwrote your
work or could run only once.

The aggregate is the element where this problem matters most. The aggregate is
the one element in the slice that carries invariants and behavior. A developer
keeps editing that code after `add` writes the scaffold. The command, the
event, and the handler are comparatively fixed once written. So the aggregate
is the element that needs a seam.

The seam has to sit cleanly on the real element model: `@domain.aggregate`,
pydantic fields, and the metaclass machinery behind them. A seam that works in
the design but fails on the real element model is worse than no seam.

## Decision

**We split the generated aggregate across a two-file base/subclass seam (the
Generation Gap pattern). We also mark every planned file with who owns it.**

The aggregate slice plans two files instead of one:

- **`aggregate_base.py`, generated.** A plain, undecorated `BaseAggregate`
  subclass, `class <Name>Base(BaseAggregate)`. It carries the structure (the
  fields) and the wiring (the `create` factory that raises the created event).
  `add` owns this file and refreshes it on every re-run.

- **`aggregate.py`, hand-owned.** The decorated subclass,
  `@domain.aggregate class <Name>(<Name>Base)`. This subclass is the registered
  aggregate, and the developer writes invariants and behavior in it. `add`
  writes this file once and never touches it again.

Long-lived model-driven tools such as OpenAPI, Protobuf and EF-Core use the
same seam. They put a generated base and a hand-owned subclass in separate
files, so regeneration never reads or writes the developer's file.

The seam composes with the element model because the decorated subclass
inherits from a `BaseAggregate` subclass. `@domain.aggregate` sees a class that
is already a `BaseAggregate` and registers it in place. It skips the flattening
rebuild it applies to a bare class. pydantic collects the base's fields through
the normal MRO. The aggregate factory collects `@invariant` methods by walking
the subclass MRO, so an invariant declared in the subclass fires. The
undecorated base registers nothing on its own, so discovery importing it during
traversal is harmless.

`add` records the seam in the plan itself, so the applier needs no naming
convention. Each `CreateFileOperation` carries an `ownership` field:

- `"generated"`: the generator owns the file; a re-run may refresh it in place.
- `"hand_owned"`: the developer owns the file; a re-run must never overwrite it.

`ownership` defaults to `"hand_owned"` because that is the safer mistake.
Wrongly preserving a file costs a stale generated file, and wrongly overwriting
one costs a developer's lost work. So a file must opt in to being overwritten.
In the aggregate slice only `aggregate_base.py` is `"generated"`; every other
file (`aggregate.py`, `commands.py`, `events.py`, `command_handlers.py`, and
the docstring-only `__init__.py`) is `"hand_owned"`, written once and then left
alone.

`add` itself still only previews the plan. An applier that honors `ownership`
on re-run comes in a later step. We define the seam now so that the applier can
follow it later.

## Consequences

A re-run of `add` is safe. A re-run refreshes the generated base. It preserves
the hand-owned subclass and every other file in the slice. The developer can
add invariants and behavior to the subclass and re-run `add` to get an improved
base without losing that work.

The applier reads its rule from the plan, and the rule is short. A
`"generated"` create op may overwrite an existing file. The applier skips a
`"hand_owned"` one if the file already exists. Because the seam is data on the
operation, neither `add` nor the applier has to encode or re-derive a path-name
convention.

An aggregate is now two files, not one. A reader has more files to keep in
mind. The base/subclass indirection is a small cost for a slice that a
developer might not re-run. In return, re-running is safe at all. Without the
seam, the developer could run `add` only once per element.

Only the aggregate is split. The command, event, and handler are single files
that mix generated structure with the developer's own fields and logic. A
re-run cannot safely refresh them, so `add` creates them once and does not
change them afterwards. If a later version needs to refresh those too, each
will need its own seam. This is a deliberate first cut, not a claim that the
aggregate is the only element that will ever want one.

## Alternatives Considered

**Keep one file with a preserved region.** Put the aggregate in a single file
and mark the region that regeneration rewrites, leaving the rest unchanged.
This is the other seam shape from the model-driven era, and it is more fragile:
it needs markers in the file, a re-run has to parse and splice around them, and
a developer editing near the boundary can break the splice. A file-level seam
needs no in-file markers and no splicing: a re-run rewrites a whole file or
skips a whole file.

**Decorate the base, subclass for logic.** Put `@domain.aggregate` on the
generated base and let the developer subclass it. The decorator then registers
the base and leaves the subclass unregistered. The developer's invariants would
be on an unregistered class, and Protean would never run them. The decorator
has to be on the hand-owned subclass.

**Generate a plain (non-`BaseAggregate`) base.** Write `class <Name>Base:` with
no framework base and decorate the subclass. On a bare class,
`@domain.aggregate` rebuilds the class onto `BaseAggregate` from its own dict
and annotations only. The base's fields are defined on a separate class in the
MRO, so the rebuild drops them. The generated base has to subclass
`BaseAggregate` for the fields to survive.

**Use a naming convention instead of an `ownership` field.** Recognize
generated files by a reserved name or directory (`_generated/`, a leading
underscore) and let the applier infer the policy. With this option the plan
does not record the seam. The seam becomes an implicit convention that the
applier has to know and every reader has to learn. Recording `ownership` on the
operation keeps the contract explicit and previewable.
