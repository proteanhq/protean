# ADR-0041: Textual event-model grammar over the IR

**Status:** Accepted

**Date:** September 2026

## Context

The event-model renderer (`protean docs generate --type=event-model --domain=<module>`,
ADR-0032) draws the domain as an EventModeling slice timeline: one slice per
aggregate cluster, reading command -> aggregate -> event -> read model. It turns
code into a diagram. The inverse does not exist. A person can write an event model
on a whiteboard, but nothing in Protean reads that model back to start a project.

Epic #1347 builds the inverse, `protean new --from-model <file>`. The command
reads a small text model and generates a first project that passes
`protean verify`, with a slice that reflects the model's aggregate, fields,
command, and event. Two components turn the text into the project:

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

This ADR fixes the grammar, the **authored-IR profile** (which IR keys the author
supplies and which the generator derives), the **vocabulary map**, and the
**conformance direction** (IR to text to IR). It does not enumerate the
parser's validation rules, the eligibility cases, or the full promotion output.
Those three form the implementation contract of the parser (#1471) and the
generator (#1472). The IR schema and the worked example below pin that
contract, and the conformance test and `protean verify` enforce it. The code
and tests state the precise contract, so this ADR records only decisions.

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
  unique within a block.
- A **field is required and has no default**, except the projection's identity
  `key`, which carries the framework identity default. Optional fields and author
  defaults are a later addition to the grammar.
- A **constraint list** is comma-separated inside the parentheses. A constraint
  is either `max_length=<positive-integer>` or the bare flag `key`.
  `max_length` is valid only on `string` and `text`, and `key` is valid only on
  an `identifier` field of a `projection`, where it marks the
  projection's identity.
- A **projector body** is one `for <ProjectionName>` line and one
  `consumes <EventName>` line. In the one-slice grammar, a projector consumes
  exactly one event. A projector that handles several events is a later
  grammar, and the eligibility check rejects a multi-handler projector from the
  round trip.

Cardinality for one slice: exactly one `aggregate`, one `command`, one `event`. The
read side is optional: at most one `projection` and one `projector`, together or not
at all. A `projection` has exactly one `key` field, the surfaced `<slug>_id`.
Its other fields come from the event by name and carry the event field's type
and constraints, so promotion populates the projection from the event alone.
The `for` and `consumes` lines name the model's own projection and event. The
parse is deterministic, infers nothing, and reports every violation with its
line number. The parser (#1471) owns the specific validation rules: name
normalization, reserved names, referential integrity, and field-shape
compatibility. The conformance test and `protean verify` on the generated
project check them.

The parser and the generator enforce the exhaustive normalization,
reserved-name, and name-collision rules (which generated symbols a field or
block name may not shadow, how a slug is recovered). They enforce them because
several of these rules depend on the project's composition root, which the
grammar does not carry. This ADR fixes the shapes; the parser and the generator
fix the full list of rules.

### The primitive types

The grammar carries eight field types, each a lexical token (`string`, `integer`)
that maps to one IR field `kind` and `type` through the table below. The tokens
belong to the grammar, but each one resolves to the IR's field model. So there
is no second field representation to keep in sync.

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

Every authored field carries `required: true` in its IR entry. The projection's
identity `key` is the one field without `required`, since it takes the framework
identity default.

The framework applies an implicit `min_length=1` to required string-based
fields (ADR-0026) as pydantic `MinLen(1)` metadata, and `IRBuilder` reads that
metadata back like any other constraint. So a required string field with no
other bound carries `min_length: 1` in the IR whether or not the author wrote
it. An explicit `min_length` of any other value stays in the IR as written. The
grammar has no `min_length` syntax, and its `required` re-derives exactly that
bound. So the emitter drops a `min_length` of 1 and refuses any other value,
including an explicit `0` (a required field that accepts the empty string has
no grammar form). An author who writes `min_length=1` by hand therefore
produces the same IR as an author who leaves it implicit. The two promote to
the same field, so the round trip holds either way.

### The authored-IR profile

The parser produces a slice-shaped fragment made of the IR's element sub-schemas:
the `aggregate`, `command`, `event`, and optional `projection`, each with a `fields`
map of **IR field entries** exactly as the table above defines them, plus a
`projector`. The author supplies only what the text carries:

- the element names and their fields (name, IR type, the two constraints);
- the read-side wiring: `for` names the projection, `consumes` names the event.

The fragment reuses the IR field model verbatim, because the two
representations drifted apart in their field models in the first draft of this
ADR. It references participants by their authored names, not by FQN. It is not
a schema-valid IR on its own.

The generator promotes the fragment to a full IR and then to code (#1472). Promotion
fills the derived keys the author never writes. These include the FQNs and `module`; each
message's `__type__` and `__version__`; `part_of`; the aggregate's injected identity
(`id`, IR kind `auto`, `auto_generated: true`); the aggregate and projection `options`
and the aggregate's `stream_category`; the projector's `aggregates`,
`stream_categories`, and `subscription` (a projector carries no `options`);
`invariants`; the empty element maps every cluster requires; the domain metadata;
the elements index; and the checksum. The generator produces the complete
builder output. Promotion is one deterministic step, and it is the same step
whether the fragment came from a text model or from `protean add`.

Because the fragment is IR field entries plus names, there is one field
vocabulary, so only the IR field model defines a field's shape. To widen the
grammar to a new IR field kind, a Protean maintainer still updates the type
table, the parser, the emitter, and the eligibility check together. The gain is
that no second field representation exists to drift from the IR.

v1 targets the default identity (`identity_type = string`, `identity_strategy =
uuid`), so the aggregate id is a UUID stored as a string and the surfaced `<slug>_id`
reference is an unconstrained `string` or `identifier`. The author writes that
`<slug>_id` field on the event and projection, and promotion does not inject
it. Promotion instead wires the generated `create` to set the field from the
aggregate's id, so promotion validates the relationship. The read side is
optional, and when the model omits it, the generator derives a default
projection and projector. The default projection mirrors the event's fields
(the `<slug>_id` becoming the `Identifier` key), and the default projector
consumes the event, so a write-side-only model still passes `protean verify`.
The derived-code mechanics (the command handler, the generation-gap seam of
ADR-0035, `Meta.stream_name`, and the per-field declaration forms the generator
writes) are the generator's contract, and `protean verify` checks them.

### The vocabulary map

Every grammar construct maps to one IR location. Most also map to a node the renderer
draws; the `field` row is the exception, mapping to an IR field entry with no drawn
node. There is no intermediate spec column: each grammar construct maps straight to an
IR location. The authored fragment keeps the grammar terms (`for`, `consumes`), which
promotion resolves to the IR keys (`projector_for`, `handlers`). `C` is a cluster's FQN
and `P` a projection group's FQN.

| Grammar construct | IR location | Renderer node |
|-------------------|-------------|---------------|
| `aggregate <Name>:` | `clusters[C].aggregate` | aggregate (state), a rectangle |
| `command <Name>:` | `clusters[C].commands[cmd]` | command (trigger), a parallelogram |
| `event <Name>:` | `clusters[C].events[evt]`, non-fact | event (result), a stadium |
| `projection <Name>:` | `projections[P].projection` | the projection in the read-model node's `Projector -> Projection` label |
| `projector <Name>:` | `projections[P].projectors[pr]` | the read-model node, a cylinder |
| `for <Projection>` | `projections[P].projectors[pr].projector_for` (an FQN promotion resolves) | the `Projector -> Projection` label |
| `consumes <Event>` | `projections[P].projectors[pr].handlers` (the event `__type__` key) | the edge from the event to the read model |
| `field <n>: <t>` | `<element>.fields[<n>]` | (fields are not drawn) |

The grammar covers the write side and read models. It does not cover the renderer's
**automations** (event handlers and process managers, the hexagon nodes) or
framework-made events (a **fact event**, or any event carrying the `auto_generated`
flag). Automations and multi-slice models are a later grammar.

### Conformance: IR to text to IR

The grammar stays aligned with the renderer's vocabulary through a structural round
trip, run as a build-time test, with no live sync between the two.

Issue #1471 adds an **emitter** that reads a full IR and a cluster FQN and
resolves the slice's read side through the top-level `projections` map. The
emitter produces grammar text for the covered subset: the participants' names,
their authored fields, and the wiring (`for`, `consumes`). Parsing that text
produces an IR fragment. The conformance test asserts the fragment matches the
slice on the covered subset. The comparison covers the shared IR element and
field shapes plus the authored wiring (the grammar's `for` and `consumes` keys,
which promotion normalizes to `projector_for` and `handlers`). Over that
covered subset the emitter and parser are inverses, checked as a property.

A cluster is **eligible** when the grammar can express its covered data: the
authored fields, the identity, and the wiring. That means authored fields
within the eight types and two constraints, the injected-id identity, the
field-set relationships between the command, event, and projection that the
worked example shows, and framework-default options. The eligibility check
ignores derived metadata the round trip does not compare (element descriptions
from docstrings, FQNs), so that metadata never makes a cluster ineligible. A
message's version is also outside the grammar, but the covered subset is
version-1 messages: the grammar has no version syntax, so promotion recreates a
version-1 message, and a command or event at any other version is ineligible.
The emitter raises on an ineligible cluster, so it never drops a covered
participant silently. The work in issue #1471 sets the exact eligibility rules,
and this conformance test enforces them. This ADR fixes that eligibility is
decided against the IR over the covered subset.

Field order is not part of the contract. The IR keys fields by name in a map, and
`IRBuilder` canonicalizes them by name, so a fragment carries no declaration order.
Generation field order is therefore non-normative: the generator emits fields in a
deterministic name order, and the round trip matches fields by name.

### The API

The grammar is implemented in `protean.scaffold.model_parser`, which carries the
two halves of the round trip described above.

`parse_model` reads a one-slice text model into a slice-shaped IR fragment: the
aggregate, its command, its event, and an optional projection and projector. The
fragment reuses the IR's own field model, so there is one field vocabulary
across the grammar, the IR and the generator. The parse is deterministic and
infers nothing. Every violation is reported with its line number, through
`ModelParseError`.

`emit_model` reads a full IR and a cluster FQN and writes grammar text back for
the covered subset. When the grammar cannot express a cluster, `emit_model`
raises `ModelEmitError` and emits no partial model. So the emitter never drops
part of a cluster silently, and the parse back to IR loses nothing. It refuses:

- a field type or constraint outside the eight types and two constraints the
  grammar carries;
- a shape the grammar cannot express;
- behaviour the grammar carries no syntax for: a non-default element option, a
  declared invariant, a published event, or a domain identity other than the
  default.

A build-time conformance test round-trips a real `to_ir()` slice through
`emit_model` and `parse_model`. The test matches the result against the worked
example below, so the grammar stays aligned with the renderer's vocabulary with
no live sync.

`parse_model` is the parser half of `protean new --from-model` (#1347). The
generator (#1472) promotes a fragment into a project, and the
[`protean add` reference](../reference/cli/project/add.md) documents it.

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

The field-entry shape is what `IRBuilder` emits: the `String` with `max_length` matches
`customer_name` in `ir/examples/ordering-ir.json`.
`protean add aggregate Order` generates the plain-`String` `order_id` reference
on the event and the `Identifier` `key` on the projection
(`scaffold/add_plan.py`, ADR-0030, ADR-0035). A hand-written aggregate in
`ordering-ir.json` instead carries its event reference as an `Identifier`.
When the generator promotes this fragment, the result is the default slice that
`protean add aggregate Order` generates. A write-side-only model omits the last
two blocks; the generator derives the default `OrderSummary` and
`OrderProjector`.

## Consequences

- **One canonical.** The text model is an authoring surface over the IR, so
  there is a single field vocabulary and a single structural contract. The
  parser (#1471) and the generator (#1472) build against the IR schema, so no
  second field representation exists to drift from it. To widen the grammar to
  a new IR field kind, a Protean maintainer still updates the grammar, parser,
  emitter, and eligibility check together, as the authored-IR profile section
  above states.
- **No middle column to drift.** The vocabulary map takes each grammar term straight to an IR key. The
  conformance round trip is IR to text to IR, a true inverse, checked as a property.
  The class of defect that comes from keeping two representations aligned by hand does
  not exist here.
- **No separate spec version.** The first draft of this ADR defined a
  `SliceSpec` type, and that type carried its own `spec_version`. The authored
  fragment is IR-shaped, so its field entries track the IR schema and need no
  parallel version. `ir_version` identifies the IR format, so it does not
  version an authored model or its contract. We version the grammar's own
  changes through this ADR.
- **The grammar is small:** eight types, two constraints, five block kinds, one slice.
  A person can write a model without a manual, and the parser can name the line of any
  mistake. The first grammar cannot express automations, multi-slice models, entities,
  or value objects; each is a later addition to this ADR and the parser together.
- **The scope line is explicit.** The generator (#1472) stays responsible for
  valid generated code, and `protean verify` checks it. This ADR bounds the
  input so that the generated project can pass `protean verify`. It does not
  list the parser's reserved-name rules or the generator's per-field emission,
  which their implementations define.

## Alternatives Considered

**A separate slice-spec type as the parse target.** The parser could return frozen
`SliceSpec` / `ElementSpec` / `SliceField` dataclasses with their own type strings,
serialized the ADR-0033 house-style way. This was the first draft of this ADR.
That design re-declares a subset of the IR's field model, so the two field
models drift. It also needs a hand-maintained vocabulary map to keep them
aligned. That map is a standing correctness liability. Reusing the IR field
model removes the second vocabulary and the map's middle column.

**Parse into a full IR document.** The grammar could target a schema-valid IR. The IR
is a fully-resolved whole-domain snapshot with many derived keys (checksums, FQNs,
message types, stream categories, empty element maps for every category) that do not
exist before code. The author writes a fragment; the generator resolves it. If
the grammar targeted a full IR, the author would have to do the resolution work
that the generator does.

**Reuse the renderer's Mermaid output as the text format.** Mermaid encodes the
diagram's shapes and edges. It leaves out the fields the generator needs, and it is
built to be drawn, so nothing parses it back. A grammar written for reading
carries the fields. Its parser reports a clear line error on a mistake.

**Round trip through a spec (spec to text to spec).** The emitter could build text
from a hand-built spec and parse it back. That checks two pieces of new code against
each other, which can share one wrong assumption. When the emitter reads from
the IR, the conformance test checks the grammar against the vocabulary the
renderer already emits. Drift between those two vocabularies is what the test
exists to catch.

**Infer the wiring from names.** The parser could attach the command and event to the
aggregate by name prefix, or invent a projection from the aggregate. A scaffold that
infers can produce code the author did not intend. A one-slice model has one
aggregate, so the command and event attach to it structurally. The author
writes the read side out or leaves it to the generator's stated default.
