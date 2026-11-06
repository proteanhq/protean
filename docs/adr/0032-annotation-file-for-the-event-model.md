# ADR-0032: Annotation File for the Event Model Renderer

**Status:** Accepted

**Date:** August 2026

## Context

The event-model renderer (`protean docs generate --type=event-model`, added under
#1442) draws the domain as an EventModeling slice timeline: one slice per aggregate
cluster, each reading command -> aggregate -> event -> consumer. Each node
stands for a domain element. The IR identifies every element by its
fully-qualified name (FQN).

The render carries structure. It does not carry the business context a person
adds: why a slice exists, the rule behind it, which team owns it. The next
regeneration destroys any context written into the generated diagram. The model
therefore stays read-only in practice. No one can use it as a shared artifact.
The annotation work in #1338 adds a layer that keeps human notes outside the
generated output and merges them back in on render.

People commit and hand-edit the notes file, so its shape is a contract. The
generated project layout is a contract for the same reason. The project-layout
ADR (ADR-0030) records that layout. The renderer change (#1338) ships the code
that reads the file. This ADR records the file's shape. With it, a reviewer of
that code, or of a project's committed notes, checks the shape against a fixed
reference.

## Decision

You write human annotations for the event model in `.protean/annotations.toml`,
a TOML file keyed by element FQN.

**The file goes in `.protean/`.** That project-state directory already holds
`ir.json`, `config.toml`, and `schemas/`. TOML matches `.protean/config.toml`
and `pyproject.toml`, so no new format enters the project. The file stays out
of the docs output directory on purpose. The generated model then stays
disposable. The notes stay under version control next to the code they
describe.

**Each entry is keyed by the element's FQN.** The key is the element's
fully-qualified name, `module.QualifiedName`, the value `protean.utils.fqn`
computes. In a project generated from the canonical layout (ADR-0030), an
`Order` aggregate in `src/myproj/example/aggregate.py` has the FQN
`myproj.example.aggregate.Order`. Quote the FQN, because TOML otherwise reads
its dots as table separators:

```toml
[annotations."myproj.example.aggregate.Order"]
note = """
Orders are the fulfillment boundary. An order cannot ship until payment
clears, so PaymentConfirmed gates the shipment slice.
"""
owner = "Fulfillment"
```

The FQN is the element's identity in the IR. A note keyed by the FQN survives
any change that leaves that identity intact: reordering elements in the source,
adding a field, regenerating the model. Renaming or moving the element changes
its FQN and breaks the link. That link should break, because a renamed element
is a different element. If the note followed the rename, it would attach stale
context to new code.

**Each entry carries two fields:**

- `note` (string, required): the business context, in free text. Why the slice exists
  and the rule behind it. A TOML multi-line string carries a paragraph.
- `owner` (string, optional): the team or person accountable for the element.

The annotation issue (#1338) names three things a person adds as context: the
why, the rule, and ownership. `note` and `owner` cover all three. A new field
changes this contract. A maintainer records the field in this ADR before the
renderer reads it.

**The renderer reports unmatched annotations.** When an entry's FQN matches no
element in the IR, the renderer lists the entry in an "unmatched annotations"
section at the end of the render. It is never dropped in silence. When a rename
leaves a note with no matching element, the note stays visible. Its author then
sees that the note needs a new key. Silently discarding a person's writing is
the worst behavior available.

## Consequences

The renderer reads a written contract instead of an ad-hoc shape. In the
renderer change (#1338), the renderer loads `.protean/annotations.toml` by FQN,
merges each note into every slice that draws its element, and appends the
unmatched-annotation report. When you review that PR, or a project's committed
annotations file, you can check the shape against this ADR.

A note is coupled to the element's FQN, so a rename breaks the link. Anyone who
renames an annotated aggregate has to give its note a new key. The
unmatched-annotations report tells them which note needs one. With the FQN as
the key, a note keeps matching its element when the element's content changes,
and stops matching when the element's identity changes.

The field set is small and fixed, so a project cannot invent structure the
renderer will not read. To add a field (a `link` to a ticket, a `status`), a
maintainer changes this ADR and the annotation loader (#1338) together. The
file's shape and the code that reads it then stay consistent.

The FQN must be quoted in TOML. An unquoted
`[annotations.myproj.example.aggregate.Order]` parses as a chain of nested
tables, not one FQN key, so the note attaches to nothing and is reported as
unmatched. The generated example and the reference documentation for
`.protean/annotations.toml` both show the quoted FQN.

## Alternatives Considered

**Write the notes into the generated model.** This option is the simplest to
render. The next regeneration destroys the notes. Lost notes are the problem
the annotation issue (#1338) exists to solve. Storing notes with the disposable
output repeats that problem, so it is the one option ruled out from the start.

**Key by a stable annotation id instead of the FQN.** An id decoupled from the
element would survive renames. An id also needs a second mechanism that binds
it to an element. That binding would be stored in the generated model or in the
source. Either place brings back the coupling problem. The FQN is already the
element's identity in the IR and needs no separate registry. A note keyed by
the FQN stops matching when its element is renamed, which is the behavior we
want.

**A top-level table per FQN, with no `[annotations]` section.** The annotations
file could key FQN tables at the top level directly. Putting the FQN tables
under `[annotations]` matches `.protean/config.toml`, where `[domains]` is
likewise a map keyed by name. The `[annotations]` table also leaves the top
level free for file-level metadata (a format version, say). A bare top-level
key then cannot be mistaken for an FQN.

**Drop unmatched annotations, or fail on them.** Dropping loses a person's
writing in silence. If the render fails on them, one stale key stops the whole
model from rendering. One rename then blocks every slice. When the renderer
reports them, the render still completes. The same output lists the stale keys.
