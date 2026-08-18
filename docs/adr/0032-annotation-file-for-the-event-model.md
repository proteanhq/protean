# ADR-0032: Annotation File for the Event Model Renderer

**Status:** Accepted

**Date:** August 2026

## Context

The event-model renderer (`protean docs generate --type=event-model`, added under
#1442) draws the domain as an EventModeling slice timeline: one slice per aggregate
cluster, each reading command -> aggregate -> event -> consumer. Each node stands for a
domain element, and the IR identifies every element by its FQN.

The render carries structure. It does not carry the business context a person adds:
why a slice exists, the rule behind it, which team owns it. Written into the
generated diagram, that context is destroyed by the next regeneration, so the model
stays read-only in practice and no one can use it as a shared artifact. #1338 adds a
layer that keeps human notes outside the generated output and merges them back in on
render.

The notes live in a file people commit and hand-edit, so its shape is a contract,
the same reason ADR-0030 records the generated project layout. #1338 ships the
renderer code that reads the file; this ADR records the file's shape, so a reviewer
of that code, or of a project's committed notes, has a fixed reference to check
against.

## Decision

Human annotations for the event model live in `.protean/annotations.toml`, a TOML
file keyed by element FQN.

**Location.** The file sits in `.protean/`, the project-state directory that already
holds `ir.json`, `config.toml`, and `schemas/`. TOML matches `.protean/config.toml`
and `pyproject.toml`, so no new format enters the project. Keeping the notes out of
the docs output directory is the point: the generated model stays disposable, and the
notes stay under version control next to the code they describe.

**Key.** Each entry is keyed by the element's fully-qualified name,
`module.QualifiedName`, the value `protean.utils.fqn` computes. In a project
generated from the canonical layout (ADR-0030), an `Order` aggregate in
`src/myproj/example/aggregate.py` has the FQN `myproj.example.aggregate.Order`. The
FQN is quoted because it contains dots, which TOML reads as table separators
otherwise:

```toml
[annotations."myproj.example.aggregate.Order"]
note = """
Orders are the fulfillment boundary. An order cannot ship until payment
clears, so PaymentConfirmed gates the shipment slice.
"""
owner = "Fulfillment"
```

The FQN is the element's identity in the IR, so a note keyed by it
survives anything that leaves that identity intact: reordering elements in the
source, adding a field, regenerating the model. Renaming or moving the element
changes its FQN and breaks the link. That link should break, because a renamed
element is a different element, and carrying a note across a rename would attach stale
context to new code.

**Field set.** An entry carries two fields:

- `note` (string, required): the business context, in free text. Why the slice exists
  and the rule behind it. A TOML multi-line string carries a paragraph.
- `owner` (string, optional): the team or person accountable for the element.

`note` and `owner` cover the three things #1338 names as the context a person adds:
the why, the rule, and ownership. A new field is a change to this contract and gets
recorded here before the renderer reads it.

**Unmatched annotations are reported.** An entry whose FQN matches no element in the
IR is listed in an "unmatched annotations" section at the end of the render. It is
never dropped in silence. A note orphaned by a rename stays visible, so the person who
wrote it sees that it needs re-keying. Silently discarding a person's writing is the
worst behavior available.

## Consequences

The renderer reads a written contract instead of an ad-hoc shape. #1338 loads
`.protean/annotations.toml` by FQN, merges each note into every slice that draws its element,
and appends the unmatched-annotation report. A reviewer of that PR, or of a project's
committed annotations file, has this ADR to check the shape against.

A note is coupled to the element's FQN, so a rename breaks the link.
Anyone renaming an annotated aggregate has to re-key its note, and the
unmatched-annotations report is how they find out. This is the trade the FQN key
makes: a note stays attached across content changes and breaks on identity changes.

The field set is small and fixed, so a project cannot invent structure the renderer
will not read. Growing it (a `link` to a ticket, a `status`) is a change to this ADR
and to #1338's loader together, which keeps the file's shape and the code that reads
it from drifting apart.

The FQN must be quoted in TOML. An unquoted
`[annotations.myproj.example.aggregate.Order]` parses as a chain of nested tables, not
one FQN key, so the note attaches to nothing and is reported as unmatched. The
generated example and the reference documentation for the file show the quoted form.

## Alternatives Considered

**Write the notes into the generated model.** Simplest to render, and destroyed on
the next regeneration. That is the problem #1338 exists to solve, so co-locating notes
with the disposable output is the one option ruled out from the start.

**Key by a stable annotation id instead of the FQN.** An id decoupled from the element
would survive renames. It also needs a second mechanism to bind the id to an element,
and that binding lives in the generated model or in the source, which puts the
coupling problem back where it started. The FQN is already the element's identity in
the IR, needs no separate registry, and its fragility across renames is the behavior
we want.

**A top-level table per FQN, with no `[annotations]` section.** The file could key FQN
tables at the top level directly. Namespacing them under `[annotations]` matches
`.protean/config.toml`, where `[domains]` is likewise a map keyed by name, and it
leaves the top level free for file-level metadata (a format version, say) without a
bare key being mistaken for an FQN.

**Drop unmatched annotations, or fail on them.** Dropping loses a person's writing in
silence. Failing turns one stale key into a render that produces nothing, which
punishes the whole model for one rename. Reporting them keeps the render working and
surfaces the staleness in the same output.
