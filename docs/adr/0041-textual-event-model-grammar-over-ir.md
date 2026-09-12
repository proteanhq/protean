# ADR-0041: Textual event-model grammar over the IR

**Status:** Accepted

**Date:** September 2026

## Context

The event-model renderer (`protean docs generate --type=event-model --domain=<module>`,
ADR-0032) draws the domain as an EventModeling slice timeline: one slice per
aggregate cluster, reading command -> aggregate -> event -> read model. It turns
code into a diagram. The inverse does not exist. A person can write an event model
on a whiteboard, but nothing in Protean reads that model back to start a project.

Epic #1347 builds the inverse: `protean new --from-model <file>` reads a small text
model and generates a first project whose slice reflects the model's aggregate,
fields, command, and event, and that passes `protean verify`. Two pieces sit
between the text and the project:

- A **parser** (#1471) turns model text into a structured form.
- A **generator** (#1472) turns that structured form into a `ChangePlan`
  (ADR-0033) the applier writes into a project.

The parser and the generator ship on different schedules, so the structured form
between them is a contract that has to be pinned in one place.

Protean already has a canonical model of a domain. The **IR** (ADR-0005) is a
portable JSON document with a versioned schema (`ir/schema/v0.2.0/schema.json`).
The renderer, the JSON-Schema / Avro / protobuf emitters (ADR-0006), the differ,
and the staleness check all read it. So this ADR settles a prior question: does the
text model need a new structured form at all, beside the IR? The answer is no. The
text model is an authoring surface over the IR.

## Decision

We define a line-oriented **textual event-model grammar** for one slice. The
grammar is a human authoring surface over the IR: the parser produces a
**slice-shaped IR fragment** that reuses the IR's own field model, and the
generator promotes that fragment to a full IR and then to code. There is no
separate spec type and no second field vocabulary.

This ADR fixes three things: the grammar, the **authored-IR profile** (which IR
keys the author supplies and which the generator derives), and the **conformance
direction** (IR to text to IR). It does not enumerate the parser's reserved-name
rules or the generator's per-field code emission. Those live with their
implementations (#1471, #1472), gated by `protean verify`.

### The grammar

A model is a sequence of blocks. Each block is a header at column zero and an
indented body:

```
aggregate Order:
    field name: string(max_length=100)

command CreateOrder:
    field name: string(max_length=100)

event OrderCreated:
    field order_id: string
    field name: string(max_length=100)

projection OrderSummary:
    field order_id: identifier(key)
    field name: string(max_length=100)

projector OrderProjector:
    for OrderSummary
    consumes OrderCreated
```

The rules:

- A **block header** is `<keyword> <Name>:` at column zero. The keyword is one of
  `aggregate`, `command`, `event`, `projection`, `projector`. `<Name>` is a Python
  identifier that is not a Python keyword. Names normalize the way `protean add`
  does: the PascalCase class name, and for an `aggregate` the snake_case `<slug>`,
  so `order_item`, `orderItem`, and `OrderItem` all name the same slice.
- A **body line** is indented under its header. A blank line and a line whose first
  non-space character is `#` are ignored, so comments and spacing are free.
- A **field line** is `field <name>: <type>` with an optional parenthesized
  constraint list: `field name: string(max_length=100)`. `<name>` is a non-keyword
  Python identifier, read verbatim, because the generator writes it as a class
  attribute. `<type>` is one of the eight primitive types below. Field names are
  unique within a block, and fields keep their declaration order for generation.
- A **field is required and has no default**, except the projection's identity
  `key`, which carries the framework identity default. Optional fields and author
  defaults are a later addition to the grammar.
- A **constraint list** is comma-separated inside the parentheses. A constraint is
  either `max_length=<positive-integer>`, valid only on `string` and `text`, or the
  bare flag `key`, valid only on an `identifier` field of a `projection`, where it
  marks the projection's identity.
- A **projector body** is one `for <ProjectionName>` line and one
  `consumes <EventName>` line.

Cardinality for one slice: exactly one `aggregate`, one `command`, one `event`. The
read side is optional: at most one `projection` and one `projector`, together or not
at all. The parse is deterministic and infers nothing. Every error names the
one-based line number and the reason.

The exhaustive normalization, reserved-name, and name-collision rules (which
generated symbols a field or block name may not shadow, how a slug is recovered)
are the parser's and generator's to enforce, because several of them depend on the
project's composition root, which the grammar does not carry. This ADR fixes the
shapes; #1471 and #1472 fix the enumeration.

### The primitive types

The grammar carries eight field types. Each names an IR field `kind` and `type`
directly. This is the single vocabulary: the grammar has no type strings of its own.

| Grammar type | IR field `kind` | IR field `type` |
|--------------|-----------------|-----------------|
| `string`     | `standard`      | `String`        |
| `text`       | `text`          | `Text`          |
| `integer`    | `standard`      | `Integer`       |
| `float`      | `standard`      | `Float`         |
| `boolean`    | `standard`      | `Boolean`       |
| `date`       | `standard`      | `Date`          |
| `datetime`   | `standard`      | `DateTime`      |
| `identifier` | `identifier`    | `Identifier`    |

The two constraints map onto the same IR field entry:

| Grammar | IR field key |
|---------|--------------|
| `max_length=<n>` | `max_length` (int) |
| `key` (flag) | `identifier: true` |

Every authored field carries `required: true`. Protean's required-field rule adds
an implicit `min_length=1` to a required `Text` or `Identifier`; that `1` is part of
the required semantics, not a third constraint, and both the source field and the
generated field carry it, so it round-trips. The projection's identity `key` is the
one field without `required`, since it takes the framework identity default.

### The authored-IR profile

The parser produces a slice-shaped fragment made of the IR's element sub-schemas:
the `aggregate`, `command`, `event`, and optional `projection`, each with a `fields`
map of **IR field entries** exactly as the table above defines them, plus a
`projector`. The author supplies only what the text carries:

- the element names and their fields (name, IR type, the two constraints);
- the read-side wiring: `for` names the projection, `consumes` names the event.

The fragment reuses the IR field model verbatim, which is where the two
representations used to drift. It references participants by their authored names,
not by FQN. It is not a schema-valid IR on its own.

The generator promotes the fragment to a full IR and then to code (#1472). Promotion
fills every derived key the author never writes: the FQNs and `module`; each
message's `__type__` and `__version__`; `part_of`; the aggregate's injected identity
(`id`, IR kind `auto`, `auto_generated: true`); the surfaced `<slug>_id` reference
the event and projection carry; the aggregate, projection, and projector `options`,
`stream_category`, `aggregates`, `stream_categories`, and `subscription` defaults;
`invariants`; the empty element maps every cluster requires; the domain metadata;
the elements index; and the checksum. Promotion is one deterministic step, and it is
the same step whether the fragment came from a text model or from `protean add`.

Because the fragment is IR field entries plus names, there is one field vocabulary
and one place to update when a field kind changes. ADR-0005's stated maintenance
cost (the generator updates when a new IR field kind appears) is paid in the IR field
model alone.

v1 targets the default identity (`identity_type = string`, `identity_strategy =
uuid`), so the aggregate id is a UUID stored as a string and the surfaced `<slug>_id`
reference is an unconstrained `string` or `identifier`. The read side is optional;
when omitted, the generator derives a default projection that mirrors the event's
fields (the `<slug>_id` becoming the `Identifier` key) and a projector that consumes
the event, so a write-side-only model still passes `protean verify`. The derived-code
mechanics (the command handler, the generation-gap seam of ADR-0035,
`Meta.stream_name`, and the per-field declaration forms the generator writes) are
#1472's contract, gated by that verify.

### The vocabulary map

Every grammar construct maps to one IR location and one node the renderer draws.
There is no intermediate spec column: the grammar names IR keys. `C` is a cluster's
FQN and `P` a projection group's FQN.

| Grammar construct | IR location | Renderer node |
|-------------------|-------------|---------------|
| `aggregate <Name>:` | `clusters[C].aggregate` | aggregate (state), a rectangle |
| `command <Name>:` | `clusters[C].commands[cmd]` | command (trigger), a parallelogram |
| `event <Name>:` | `clusters[C].events[evt]`, non-fact | event (result), a stadium |
| `projection <Name>:` | `projections[P].projection` | the projection in the read-model node's `Projector -> Projection` label |
| `projector <Name>:` | `projections[P].projectors[pr]` | the read-model node, a cylinder |
| `for <Projection>` | `projectors[pr].projector_for` (an FQN promotion resolves) | the `Projector -> Projection` label |
| `consumes <Event>` | `projectors[pr].handlers` (the event `__type__` key) | the edge from the event to the read model |
| `field <n>: <t>` | `<element>.fields[<n>]` | (fields are not drawn) |

The grammar covers the write side and read models. It does not cover the renderer's
**automations** (event handlers and process managers, the hexagon nodes) or
framework-made events (a **fact event**, or any event carrying the `auto_generated`
flag). Automations and multi-slice models are a later grammar.

### Conformance: IR to text to IR

The grammar stays aligned with the renderer's vocabulary through a structural round
trip, run as a build-time test, with no live sync between the two.

#1471 adds an **emitter** that reads one cluster of an IR and produces grammar text
for the covered subset: the participants' names, their authored fields, and the
wiring (`for`, `consumes`). Parsing that text produces an IR fragment. The
conformance test asserts the fragment matches the cluster on the covered subset.
Because both sides are IR, the emitter and parser are inverses over one
representation, and the check is a property, not a hand-maintained table.

A cluster is **eligible** only when its covered subset is expressible in the
grammar: fields within the eight types and two constraints; the identity is the
injected id (`auto_generated: true`); the field-set relationships hold (the command's
fields equal the aggregate's, the event's equal the aggregate's plus `<slug>_id`, the
projection's are `<slug>_id` plus a subset of the event's); and the options,
subscription, and stream category are the framework defaults. A cluster carrying
anything the grammar cannot say (a container or `Status` field, a numeric bound, a
`choices` or `unique` marker, a custom stream category, an authored identity) is
ineligible, and the emitter raises on it, so it never drops a covered participant
silently. The precise
eligibility enumeration and the project-contextual name-collision rules are #1471 and
#1472 implementation detail; this ADR fixes that eligibility is decided against the
IR and that the round trip compares the covered subset.

Field order is not compared. The IR keys fields by name in a map, an authored model
keeps declaration order for generation, and the round trip matches fields by name.

### Normative worked example

This is the reference the downstream issues test against. The model text is the Order
slice above. It parses to this fragment (IR field entries verbatim; participants
referenced by name; the `fields` maps are unordered):

```json
{
  "aggregate": {
    "name": "Order",
    "fields": {
      "name": {"kind": "standard", "type": "String", "max_length": 100, "required": true}
    }
  },
  "command": {
    "name": "CreateOrder",
    "fields": {
      "name": {"kind": "standard", "type": "String", "max_length": 100, "required": true}
    }
  },
  "event": {
    "name": "OrderCreated",
    "fields": {
      "order_id": {"kind": "standard", "type": "String", "required": true},
      "name": {"kind": "standard", "type": "String", "max_length": 100, "required": true}
    }
  },
  "projection": {
    "name": "OrderSummary",
    "fields": {
      "order_id": {"kind": "identifier", "type": "Identifier", "identifier": true},
      "name": {"kind": "standard", "type": "String", "max_length": 100, "required": true}
    }
  },
  "projector": {
    "name": "OrderProjector",
    "for": "OrderSummary",
    "consumes": "OrderCreated"
  }
}
```

The field entries are exactly the shape `IRBuilder` emits (`ir/examples/ordering-ir.json`):
a `String` with `max_length`, a plain-`String` `order_id` reference on the event, and
an `Identifier` `key` on the projection. Promoted, this is the slice `protean add
aggregate Order` produces today (ADR-0030, ADR-0035). A write-side-only model omits
the last two blocks; the generator derives the default `OrderSummary` and
`OrderProjector`.

## Consequences

- **One canonical.** The text model is an authoring surface over the IR, so there is
  a single field vocabulary and a single structural contract. #1471 and #1472 build
  against the IR schema. When a field kind is added, it is updated in the IR field
  model alone.
- **No middle column to drift.** The vocabulary map is grammar term to IR key. The
  conformance round trip is IR to text to IR, a true inverse, checked as a property.
  The class of defect that comes from keeping two representations aligned by hand does
  not exist here.
- **Versioning comes from the IR.** An authored model versions with `ir_version` and
  gets the ADR-0033 / ADR-0040 diff and compatibility machinery, with no separate spec
  version to maintain.
- **The grammar is small:** eight types, two constraints, five block kinds, one slice.
  A person can write a model without a manual, and the parser can name the line of any
  mistake. The first grammar cannot express automations, multi-slice models, entities,
  or value objects; each is a later addition to this ADR and the parser together.
- **The scope line is explicit.** The generated code's validity stays #1472's
  contract, gated by `protean verify`. This ADR bounds the input so that gate is
  reachable; it does not enumerate the parser's reserved-name rules or the generator's
  per-field emission, which live with their implementations.

## Alternatives Considered

**A separate slice-spec type as the parse target.** The parser could return frozen
`SliceSpec` / `ElementSpec` / `SliceField` dataclasses with their own type strings,
serialized the ADR-0033 house-style way. This was the first draft of this ADR. It
re-declares a subset of the IR's field model, so the two drift, and it needs a
hand-maintained vocabulary map to stay aligned. That map is a standing correctness
liability. Reusing the IR field model removes the second vocabulary and the map's
middle column.

**Parse into a full IR document.** The grammar could target a schema-valid IR. The IR
is a fully-resolved whole-domain snapshot with many derived keys (checksums, FQNs,
message types, stream categories, empty element maps for every category) that do not
exist before code. The author writes a fragment; the generator resolves it. Requiring
a full IR from the author would push the resolution work onto the person.

**Reuse the renderer's Mermaid output as the text format.** Mermaid encodes the
diagram's shapes and edges. It leaves out the fields the generator needs, and it is
built to be drawn, so nothing parses it back. A grammar written for reading carries
the fields and reports a clear line error on a mistake.

**Round trip through a spec (spec to text to spec).** The emitter could build text
from a hand-built spec and parse it back. That checks two pieces of new code against
each other, which can share one wrong assumption. Emitting from the IR checks the
grammar against the vocabulary the renderer already emits, which is the drift the
conformance test exists to catch.

**Infer the wiring from names.** The parser could attach the command and event to the
aggregate by name prefix, or invent a projection from the aggregate. A scaffold that
infers can produce code the author did not intend. A one-slice model has one
aggregate, so the command and event attach to it structurally, and the read side is
written out or left to the generator's stated default.
