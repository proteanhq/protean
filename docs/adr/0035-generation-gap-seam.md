# ADR-0035: Generation-gap seam between generated wiring and hand-owned logic

**Status:** Accepted

**Date:** August 2026

## Context

`protean add <element> <name>` plans a new element slice for an existing project.
The first version plans an aggregate slice: the aggregate, its create command, its
created event, and the command handler that ties them together (see ADR-0030 for
the canonical layout `add` writes into, and ADR-0033 for the `ChangePlan` it
produces).

`add` is meant to be re-run. A template improves, a field is added, the generator
learns a new default, and the developer runs `add` again for the same element to
pick up the refreshed wiring. That is only safe if regeneration cannot destroy the
code the developer wrote in the meantime. If generated wiring and hand-written
logic share a file, a re-run has to either overwrite the developer's edits or merge
them. Both are the regeneration trap that sank a generation of model-driven tools:
either the tool clobbers your work, or it becomes a one-shot stamp you can never run
again.

The aggregate is where this bites. It is the one element in the slice that carries
invariants and behavior, the code a developer keeps editing after the scaffold is
in place. The command, the event, and the handler are comparatively fixed once
written. So the aggregate is the element that needs a seam.

The seam has to sit cleanly on the real element model: `@domain.aggregate`, pydantic
fields, and the metaclass machinery behind them. A seam that only works on paper is
worse than none.

## Decision

**We split the generated aggregate across a two-file base/subclass seam (the
Generation Gap pattern) and mark every planned file with who owns it.**

The aggregate slice plans two files instead of one:

- **`aggregate_base.py`, generated.** A plain, undecorated `BaseAggregate`
  subclass, `class <Name>Base(BaseAggregate)`, carrying the structure (the fields)
  and the wiring (the `create` factory that raises the created event). `add` owns
  this file and refreshes it on every re-run.

- **`aggregate.py`, hand-owned.** The decorated subclass,
  `@domain.aggregate class <Name>(<Name>Base)`. This is the registered aggregate,
  and it is where the developer's invariants and behavior go. `add` writes this file
  once and never touches it again.

This is the same seam the durable model-driven tools use (OpenAPI, Protobuf,
EF-Core): a generated base and a hand-owned subclass in separate files, so
regeneration never reads or writes the human's file.

It composes with the element model because the decorated subclass inherits from a
`BaseAggregate` subclass. `@domain.aggregate` sees a class that is already a
`BaseAggregate` and registers it in place, without the flattening rebuild it applies
to a bare class. pydantic collects the base's fields through the normal MRO, and the
aggregate factory collects `@invariant` methods by walking the subclass MRO, so an
invariant declared in the subclass fires. The undecorated base registers nothing on
its own, so discovery importing it during traversal is harmless.

The seam is recorded on the plan, not left to a naming convention. Each
`CreateFileOperation` carries an `ownership` field:

- `"generated"`: the generator owns the file; a re-run may refresh it in place.
- `"hand_owned"`: the developer owns the file; a re-run must never overwrite it.

`ownership` defaults to `"hand_owned"`, the safe side: the cost of wrongly
preserving a file is a stale generated file, while the cost of wrongly overwriting
one is a developer's lost work, so a file must opt in to being overwritten. In the
aggregate slice only `aggregate_base.py` is `"generated"`; every other file
(`aggregate.py`, `commands.py`, `events.py`, `command_handlers.py`, and the
docstring-only `__init__.py`) is `"hand_owned"`, written once and then left alone.

`add` itself still only previews; an applier that honors `ownership` on re-run is a
later step. This ADR fixes the seam the applier will follow.

## Consequences

A re-run of `add` is safe. The generated base is refreshed; the hand-owned subclass,
and every other file in the slice, is preserved. The developer can add invariants and
behavior to the subclass and re-run `add` to pick up an improved base without losing
that work.

The applier's rule is simple and reads off the plan: a `"generated"` create op may
overwrite an existing file; a `"hand_owned"` one is skipped if the file already
exists. There is no path-name convention to encode or re-derive, because the seam is
data on the operation.

An aggregate is now two files, not one. That is more files for a reader to hold, and
the base/subclass indirection is a small cost for a slice a developer might not
re-run. The payoff is that re-running is safe at all; without the seam, `add` would
be a one-shot stamp.

Only the aggregate is split. The command, event, and handler are single files that
mix generated structure with the developer's own fields and logic, so a re-run
cannot safely refresh them; it creates them once and leaves them alone. If a later
version needs to refresh those too, each will need its own seam. This is a
deliberate first cut, not a claim that the aggregate is the only element that will
ever want one.

## Alternatives Considered

**One file with a preserved region.** Keep the aggregate in a single file and mark a
region regeneration rewrites, leaving the rest. This is the other seam shape from the
model-driven era, and it is more fragile: it needs markers in the file, a re-run has
to parse and splice around them, and a developer editing near the boundary can break
the splice. A file-level seam needs no in-file markers and no splicing: a re-run
rewrites a whole file or skips a whole file.

**Decorate the base, subclass for logic.** Put `@domain.aggregate` on the generated
base and let the developer subclass it. This registers the base, not the subclass, so
the developer's invariants would sit on an unregistered class and never run. The
decorator has to be on the hand-owned subclass.

**A plain (non-`BaseAggregate`) generated base.** Generate `class <Name>Base:` with
no framework base and decorate the subclass. `@domain.aggregate` on a bare class
rebuilds it onto `BaseAggregate` from the class's own dict and annotations only, so
the base's fields, defined on a separate class in the MRO, are dropped. The generated
base has to subclass `BaseAggregate` for the fields to survive.

**A naming convention instead of an `ownership` field.** Recognize generated files by
a reserved name or directory (`_generated/`, a leading underscore) and let the
applier infer the policy. This keeps the seam out of the plan but pushes it into an
implicit convention the applier has to know and every reader has to learn. Recording
`ownership` on the operation keeps the contract explicit and previewable.
