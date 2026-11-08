# ADR-0035: Generation-gap seam between generated wiring and hand-owned logic

**Status:** Accepted

**Date:** August 2026

## Context

`protean add <element> <name>` plans a new element slice for an existing project.
The first version plans an aggregate slice: the aggregate, its create command,
its created event, and the command handler that connects them. ADR-0030 defines
the canonical layout `add` writes into, and ADR-0033 defines the `ChangePlan`
that `add` produces.

`add` is meant to be re-run. When a template improves, a field is added, or the
generator gains a new default, the developer runs `add` again for the same
element to pick up the refreshed wiring. That is only safe if regeneration
cannot destroy the code the developer wrote in the meantime. If generated
wiring and hand-written logic share a file, a re-run has to either overwrite
the developer's edits or merge them. Model-driven tools of an earlier
generation failed on this choice: either the tool overwrote the developer's
work, or the developer could run it only once.

This problem arises in the aggregate. It is the one element in the slice that carries
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
  `@domain.aggregate class <Name>(<Name>Base)`. This subclass is the registered
  aggregate, and the developer writes invariants and behavior in it. `add`
  writes this file once and never touches it again.

Long-lived model-driven tools such as OpenAPI, Protobuf, and EF-Core use the
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
the docstring-only `__init__.py`) is `"hand_owned"`, written once and then
left alone.

`add` itself still only previews; an applier that honors `ownership` on re-run is a
later step. We define the seam now so that the applier can follow it later.

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
re-run. The payoff is that re-running `add` is safe at all; without the seam,
the developer could safely run `add` only once per element.

Only the aggregate is split. The command, event, and handler are single files
that mix generated structure with the developer's own fields and logic. A
re-run cannot safely refresh them, so `add` creates them once and does not
change them afterwards. If a later version needs to refresh those too, each
will need its own seam. This is a deliberate first cut, not a claim that the
aggregate is the only element that will ever want one.

## Alternatives Considered

**One file with a preserved region.** Keep the aggregate in a single file and mark a
region regeneration rewrites, leaving the rest. This is the other seam shape from the
model-driven era, and it is more fragile: it needs markers in the file, a re-run has
to parse and splice around them, and a developer editing near the boundary can break
the splice. A file-level seam needs no in-file markers and no splicing: a re-run
rewrites a whole file or skips a whole file.

**Decorate the base, subclass for logic.** Put `@domain.aggregate` on the generated
base and let the developer subclass it. The decorator then registers the base
and leaves the subclass unregistered, so the developer's invariants would be on
an unregistered class and would never run. The decorator has to be on the
hand-owned subclass.

**A plain (non-`BaseAggregate`) generated base.** Generate `class <Name>Base:` with
no framework base and decorate the subclass. On a bare class,
`@domain.aggregate` rebuilds the class onto `BaseAggregate` from its own dict
and annotations only. The base's fields are defined on a separate class in the
MRO, so the rebuild drops them. The generated base has to subclass
`BaseAggregate` for the fields to survive.

**A naming convention instead of an `ownership` field.** Recognize generated files by
a reserved name or directory (`_generated/`, a leading underscore) and let the
applier infer the policy. With this option the plan does not record the seam,
but the seam becomes an implicit convention that the applier has to know and
every reader has to learn. Recording `ownership` on the operation keeps the
contract explicit and previewable.
