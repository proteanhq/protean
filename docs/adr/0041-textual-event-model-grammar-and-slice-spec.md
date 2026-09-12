# ADR-0041: Textual event-model grammar and slice-spec vocabulary

**Status:** Accepted

**Date:** September 2026

## Context

The event-model renderer (`protean docs generate --type=event-model`, ADR-0032)
draws the domain as an EventModeling slice timeline: one slice per aggregate
cluster, each reading command -> aggregate -> event -> consumer. It turns code
into a diagram. The inverse does not exist. A person can write an event model on a
whiteboard, but nothing in Protean reads that model back to start a project from
it.

Epic #1347 builds that inverse: `protean new --from-model <file>` reads a small
text model and generates a first project whose slice reflects the model's
aggregate, fields, command, and event, and that passes `protean verify`. Two
pieces sit between the text and the project:

- A **parser** (#1471) turns model text into a structured form.
- A **generator** (#1472) turns that structured form into a `ChangePlan`
  (ADR-0033) the applier writes into a project.

The parser and the generator ship on different schedules, so the structured form
they pass between them is a contract. The parser produces it and the generator
reads it, so the two build against one fixed shape. That shape is the **slice
spec**.

Two constraints shape the grammar and the spec. The grammar has to line up with
the vocabulary the renderer already emits, so a model a person reads out of a
rendered diagram and a model a person writes to seed a project describe one thing.
And the round trip has to be checkable: render a known IR to model text, parse it
back, and confirm the parsed spec still matches the source. Without that check the
grammar and the renderer's vocabulary drift apart release by release, and the text
model stops describing what the renderer draws.

This ADR fixes the grammar, the slice spec, and the map between them and the IR,
so #1471 and #1472 build against one reference.

## Decision

We define a line-oriented **textual event-model grammar** for one slice, a frozen
**`SliceSpec`** dataclass the parser produces and the generator consumes, and a
**vocabulary map** that ties every grammar term to the slice-spec field and the IR
key it stands for.

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
  `aggregate`, `command`, `event`, `projection`, `projector`. `<Name>` is a valid
  Python identifier that is not a Python keyword, read verbatim and used as the
  generated class name. The aggregate name also derives a snake_case `<slug>` by the
  word split `add_plan.py` uses, and the slug must itself be a valid non-keyword
  identifier; the parser rejects a name whose slug is not, such as `Class`, whose
  slug `class` is a keyword.
- A **body line** is indented under its header. A blank line and a line whose
  first non-space character is `#` are ignored, so comments and spacing are free.
- A **field line** is `field <name>: <type>` with an optional parenthesized
  constraint list: `field name: string(max_length=100)`. `<name>` is a valid
  Python identifier that is not a Python keyword, read verbatim, because the
  generator writes it as a class attribute. Field names are unique within a block;
  a duplicate is an error. A field name may not start with an underscore or use the
  pydantic `model_` prefix, and it may not shadow a member the generated class
  carries in its block, whether the template defines it (`id` and `create` in an
  `aggregate`, `Meta` in a `projection`) or the block's framework base provides it:
  `BaseAggregate` for an aggregate (including `raise_`), `BaseMessageType` for a
  command and an event (including `payload`), and `BaseProjection` for a projection.
  It also may not collide with a name the template binds locally around the field,
  such as the `create` factory's `cls` parameter. The parser checks each field name
  against every name its block's generated code binds, in code, so the reserved set
  follows the templates and does not drift from a list written here. An `aggregate`
  also reserves `<slug>_id`, the identity reference the generator injects into the
  event, so an aggregate cannot declare a field that the id wiring already fills.
  `<type>` is one of the eight primitive types below, and fields keep their
  declaration order for generation.
- A **field is required and has no default,** and the grammar does not express
  optional fields or author-supplied defaults. `field name: string` maps to a bare
  `str` annotation, a required, unbounded string that the IR records as a `String`
  with no `max_length`. The projection's `key` field is an `identifier`, and the
  generator emits it as `Identifier(identifier=True)`, whose identity default_factory
  the framework supplies. A projection whose identity is another field type (an IR
  `String(identifier=True)`, say) is outside the grammar, and the emitter rejects
  that cluster. Optional fields and author defaults are a later addition to the
  grammar.
- A **constraint list** sits in the parentheses, comma-separated, with insignificant
  whitespace around each entry: `string(max_length=100)`, `identifier(key)`. A
  constraint is either `max_length=<positive-integer>` or the bare flag `key`.
  `max_length` applies only to `string` and `text`, and its value is a positive
  integer; the parser rejects it on any other type, because Protean drops
  `max_length` on a non-string field, and rejects a zero or negative value. `key`
  applies only to an `identifier` field of a `projection`, where it marks the
  projection's identity field; the parser rejects `key` on any other type or in any
  other block. A constraint name appears at most once in a
  list; a duplicate, such as `string(max_length=10, max_length=20)` or
  `identifier(key, key)`, is an error.
- A **projector body** is one `for <ProjectionName>` line naming the projection it
  feeds, and one `consumes <EventName>` line naming the event it reads.

Cardinality for one slice: exactly one `aggregate`, one `command`, and one
`event`. The read side is optional: a model has at most one `projection` and one
`projector`, together or not at all. A `projection` without a `projector`, the
reverse, or a second `projection` or `projector`, is an error, since the spec holds
one of each. A `projection` carries exactly one `key` field. Block
names are unique across the slice, because the generated command handler and
projector import the aggregate, command, event, and projection by their bare class
names; a name shared by two blocks is an error. A block name, and the aggregate's
`<slug>`, also may not collide with a symbol the generated modules bind: the `handle`
and `on` decorators and the other helper imports, the composition-root domain
variable (so a `<slug>` of `domain` is rejected), a local variable the templates bind
(the command handler's `repo`, so a `<slug>` of `repo` is rejected), or a name the
generator supplies for an omitted read side (`<Aggregate>Summary`,
`<Aggregate>Projector`). The parser checks these against the symbols the generated
modules bind, in code, the same closed way it checks field names.

The parse is deterministic and infers nothing. Names are preserved as written. A
`for` line must name the model's projection, and the `consumes` line must name the
model's event; a dangling reference is an error. Every error names the one-based
line number and the reason. An error that has an offending line names it; a
structural error with no single line (a missing `aggregate`, `command`, `event`, or
a missing half of the read side) is reported at the line after the input, and a
cross-block error is anchored to the header line of the block that breaks the rule.

### The primitive types

The grammar carries eight field types. Each maps to one IR field type (the value
`ir/builder.py` records) and one Protean field:

| Grammar type | Spec `type` | IR field `type` | Protean field |
|--------------|-------------|-----------------|---------------|
| `string`     | `"string"`  | `String`        | `String`      |
| `text`       | `"text"`    | `Text`          | `Text`        |
| `integer`    | `"integer"` | `Integer`       | `Integer`     |
| `float`      | `"float"`   | `Float`         | `Float`       |
| `boolean`    | `"boolean"` | `Boolean`       | `Boolean`     |
| `date`       | `"date"`    | `Date`          | `Date`        |
| `datetime`   | `"datetime"`| `DateTime`      | `DateTime`    |
| `identifier` | `"identifier"` | `Identifier` | `Identifier`  |

Every generated field is required, unsanitized, and unbounded unless it declares
`max_length`. The generator pins the field parameters to reach that; it does not lean
on the `String()`, `Text()`, or `Identifier()` factory defaults, which would add
`max_length=255`, `sanitize=True`, or an optional `default`. `string` uses a bare
`str` annotation (IR type `String`), which is already required, unbounded, and
unsanitized; `text` uses `Text(sanitize=False, required=True)` (IR type `Text`),
keeping the text kind. An IR field that carries a `sanitize` flag or resolves to an
optional default is not representable, and the emitter rejects its cluster.

The auto-generated `id` an aggregate carries (IR kind `auto`, type `Auto`) is not
a grammar type. The framework injects it, no one writes it, so the grammar does
not carry it and the emitter skips it.

### The slice spec

The parser produces a `SliceSpec`, homed in `protean.scaffold.slice_spec`. It
follows the IR serialization house style ADR-0033 sets: frozen dataclasses
serialized by an explicit `to_dict`/`from_dict` JSON dump. pydantic stays reserved
for domain elements. The type names are fixed here so #1471 returns them and #1472
imports them:

- `SliceField(name: str, type: str, max_length: int | None = None, identifier:
  bool = False)`: one field. `type` is a grammar type string from the table above.
  `max_length` and `identifier` carry the two constraints. The name distinguishes
  it from `protean.fields.FieldSpec`, the framework's own field-declaration
  carrier.
- `ElementSpec(name: str, fields: tuple[SliceField, ...])`: an element with fields.
  The aggregate, the command, the event, and the projection are each an
  `ElementSpec`. `fields` keeps declaration order.
- `ProjectorSpec(name: str, projection: str, consumes: str)`: the projector, the
  projection name it feeds, and the event name it reads. A later multi-event
  grammar widens `consumes`, which is a `spec_version` bump.
- `SliceSpec(aggregate: ElementSpec, command: ElementSpec, event: ElementSpec,
  projection: ElementSpec | None, projector: ProjectorSpec | None, spec_version:
  str)`: the whole slice. `projection` and `projector` are `None` together when
  the model omits the read side.

The serialized form carries a `spec_version` marker, starting at `0.1.0`, so a
generator built against an older spec meets a newer one and fails at the version
check. `from_dict` rejects an unknown `spec_version`, an unknown field type, and
any missing or wrongly-typed required field with a clear `ValueError`, the way
`load_config` and `from_dict` on the `ChangePlan` reject malformed input. Sparse
keys (`max_length`, `identifier`) are omitted when unset, matching the IR field
entry.

The generator (#1472) fills in everything the slice needs that the model does not
carry: the command handler, the generation-gap base/subclass seam (ADR-0035), the
package `__init__.py`, and the aggregate's injected identity. It wires fields by
name: the command handler creates the aggregate from the command's fields, the
aggregate raises the event with its identity and its same-named fields, and the
projector copies each projection field from the event field of the same name. The
aggregate's identity travels as a field named `<slug>_id`: the generated `create`
raises the event with `<slug>_id` set to the aggregate's `id`, and the projection's
`key` is that same `<slug>_id`. v1 targets the default string (UUID) identity; a
project configured for integer identity (ADR-0021) is out of scope. The aggregate id
is then a string, so `<slug>_id` is an unconstrained `string` or `identifier`, with
no `max_length`, since the id is a UUID. The command declares the aggregate's
authored fields, the event declares those fields plus `<slug>_id`, and the projection
declares `<slug>_id` and a subset of the event's fields. The identity `<slug>_id` is
the one field allowed to differ across blocks, an unconstrained `string` or
`identifier` on each side (typically a `string` on the event and the projection's
`identifier` key). Every other field shared by name carries the same type and
constraints on all sides, so the copied value fits. These are parser rules the
parser enforces on its own: it rejects a model whose event
omits `<slug>_id`, whose `<slug>_id` is not an unconstrained `string` or
`identifier`, whose command and aggregate field sets differ, whose event field set is
not exactly the aggregate's fields plus `<slug>_id`, whose projection reads a field
the event does not declare, whose projection `key` is a field other than `<slug>_id`,
or that declares a shared non-identity field name differently in two blocks. Generation is then a name lookup with no inference. Field sets that diverge further, such as a
denormalizing projection, are a later addition with explicit mappings.

When the read side is `None`, the generator supplies a default projection that
mirrors the event's fields, with the event's str-based `<slug>_id` becoming the
projection's `Identifier(identifier=True)` key, and a default projector that consumes
the event and copies each field by name. The derivation reads the event, so a
write-side model that carries the `<slug>_id` identity field generates a valid read
side, and the project passes `protean verify`.

### The vocabulary map

Every grammar construct maps to one slice-spec field, one IR location, and one
node the renderer draws. In the IR paths, `C` is a cluster's FQN and `P` is a
projection group's FQN (`ir/builder.py` keys the group by the projection's own FQN);
`projections[P]` is that group entry, holding the `projection` element and the
`projectors` map, so the projector name reads `projections[P].projectors[pr].name`.

| Grammar construct | Slice-spec field | IR location | Renderer node |
|-------------------|------------------|-------------|---------------|
| `aggregate <Name>:` | `SliceSpec.aggregate.name` | `clusters[C].aggregate.name` | aggregate (state), a rectangle |
| `field <n>: <t>` under an element | `<element>.fields[]` | `<element>.fields[n]` | (fields are not drawn; the diff reports `field <n>`) |
| `command <Name>:` | `SliceSpec.command.name` | `clusters[C].commands[cmd]` | command (trigger), a parallelogram |
| `event <Name>:` | `SliceSpec.event.name` | `clusters[C].events[evt]`, non-fact | event (result), a stadium |
| `projection <Name>:` | `SliceSpec.projection.name` | `projections[P].projection.name` | read model, a cylinder |
| `projector <Name>:` | `SliceSpec.projector.name` | `projections[P].projectors[pr].name` | the read-model node |
| `for <Projection>` | `SliceSpec.projector.projection` | `projectors[pr].projector_for` (an FQN the emitter shortens to the class name) | the `Projector -> Projection` node label |
| `consumes <Event>` | `SliceSpec.projector.consumes` | `projectors[pr].handlers` (the one event `__type__` key in a one-slice model) | the edge from the event to the read model |

Two constraints map onto the IR field entry:

| Grammar | Spec key | IR field key |
|---------|----------|--------------|
| `max_length=<n>` | `max_length` (int) | `max_length` |
| `key` (flag) | `identifier` (bool) | `identifier` |

The grammar covers the renderer's write-side vocabulary and its read models. It
does not cover the renderer's **automations** (event handlers and process
managers, the hexagon nodes), and it does not cover **fact events**, which the
renderer filters and the framework auto-generates. A one-slice model is a command,
an aggregate, an event, and an optional read model. Automations and multi-slice
models are a later grammar.

### Conformance: IR to text to spec

The grammar stays aligned with the renderer's vocabulary through a structural
round trip, run as a build-time test, with no live sync between the two.

#1471 adds an **emitter** that reads the IR (the same dict the renderer reads) and
one cluster, and produces grammar text for that slice. The emitter reads only what
the vocabulary map covers: the aggregate and its authored fields, the command, the
non-fact event, and the read model's projection and projector with the event it
consumes. It renders every name by its short form, the same `short_name` the
renderer applies: `projector_for` is stored as a full projection FQN, and the
emitter shortens it to the class name the `for` line carries. It recovers the
`consumes` name by matching the projector's `handlers` key back to the slice's
event. It skips the injected `id`, element options, and every element the grammar
does not carry (entities, value objects, repositories, database models, command
handlers, application services, queries, automations, fact events).

The emitter's precondition is one closed rule: it emits a cluster only when the
emitted grammar text parses back, under every parser rule above, to a spec that
matches the cluster. The cluster must therefore satisfy the cross-block field-set and
identity rules as well as the per-field shape: exactly one command and one non-fact
event; the field-set equality (command equals aggregate, event equals aggregate plus
`<slug>_id`, projection equals `<slug>_id` plus a subset of the event); either no
read side or one projection with exactly one identity field, of type `identifier`,
and one projector; a
projector whose `handlers` route only that event, whose `aggregates` are exactly the
slice's aggregate, and whose `stream_categories` are the default that aggregate
derives, with no extra category or subscription override; distinct element short
names; and every field within the eight types and two constraints, required and
without an author default, with the projection's `identifier` key the one exception,
which carries the framework identity default. Anything the grammar cannot carry
makes the cluster ineligible: a field whose IR `type` is outside the eight (`Status`,
a `List` or `Dict` container), a constraint or flag the grammar has no syntax for (a
`sanitize` flag, an optional or defaulted field), an extra or mismatched field, a
second projection or projector, a projector wired to another aggregate's events or a
broader subscription, an identity beyond the default string, message metadata the
grammar has no syntax for (a non-default `__version__`, a publication, supersession,
or deprecation option), or a field named something the grammar reserves. The emitter
judges a field on its IR `type`, so a Python type the builder already collapsed to a
grammar type carries as that type: `IRBuilder._resolve_type_name` falls back to
`String` for an unmapped type such as `decimal.Decimal`, so that field is `String` in
the IR and round-trips as grammar `string`. That collapse is the builder's, before
the emitter, and outside this round trip. The emitter raises on an ineligible cluster,
so it never emits text that drops or distorts what the cluster holds, and conformance
cannot pass while the emitter loses model elements.

`_extract_fields` sorts a cluster's fields by name, so the IR does not keep the
order the fields were declared in. The emitter emits fields in the IR's order, and
the conformance test matches fields by name. An authored model keeps its
declaration order for generation; only this round-trip check reads fields without
regard to order.

The conformance test renders a known IR to model text, parses that text to a
`SliceSpec`, and asserts the spec matches the slice as the vocabulary map reads it
from the IR. A mismatch means the grammar and the IR vocabulary have drifted, and
the test fails until they agree. The existing Mermaid and GWT renderer stays as it
is; the emitter is a separate function producing grammar text.

### Normative worked example

This is the reference the downstream issues test against. The model text is the
Order slice above. It parses to exactly this spec (shown in serialized form):

```json
{
  "spec_version": "0.1.0",
  "aggregate": {
    "name": "Order",
    "fields": [
      {"name": "name", "type": "string", "max_length": 100}
    ]
  },
  "command": {
    "name": "CreateOrder",
    "fields": [
      {"name": "name", "type": "string", "max_length": 100}
    ]
  },
  "event": {
    "name": "OrderCreated",
    "fields": [
      {"name": "order_id", "type": "string"},
      {"name": "name", "type": "string", "max_length": 100}
    ]
  },
  "projection": {
    "name": "OrderSummary",
    "fields": [
      {"name": "order_id", "type": "identifier", "identifier": true},
      {"name": "name", "type": "string", "max_length": 100}
    ]
  },
  "projector": {
    "name": "OrderProjector",
    "projection": "OrderSummary",
    "consumes": "OrderCreated"
  }
}
```

The example mirrors the fields `protean add aggregate Order` generates today
(ADR-0030, ADR-0035): the event carries a plain-string `order_id` reference, and
the projection carries an `Identifier` key.

A write-side-only model omits the last two blocks:

```
aggregate Order:
    field name: string(max_length=100)

command CreateOrder:
    field name: string(max_length=100)

event OrderCreated:
    field order_id: string
    field name: string(max_length=100)
```

It parses to the same spec with `"projection": null` and `"projector": null`. That
write-side-only spec is what #1472's default `add` path passes. The generator
supplies the default `OrderSummary` projection and `OrderProjector`, which
reproduces the slice `plan_add_slice` emits today byte-for-byte.

## Consequences

- #1471 and #1472 build against one shape. The parser returns a `SliceSpec` and
  the generator imports it, so the contract between them is fixed in one place. The
  worked example is the fixture both test against.
- The vocabulary map is a single table both the emitter and the parser read, so a
  grammar term and the IR key it stands for cannot drift apart quietly. The
  conformance round trip fails when they do.
- The grammar is small: eight primitive types, two constraints, five block kinds,
  one slice. A person can write a model without a manual, and the
  parser can name the line of any mistake. The cost is that the first grammar
  cannot express automations, multi-slice models, entities, or value objects; each
  is a later addition to this ADR and to the parser together.
- `spec_version` versions the contract. A generator meeting a spec it does not
  understand fails at `from_dict` before it writes any files. The cost is that a
  change to the spec shape bumps the version and updates both sides.
- The read side is optional, so the same generator drives the greenfield path (a
  full model) and the deterministic `add` path (a default spec). One generator
  serves both callers, so the default slice needs no separate code path.
- This ADR fixes the grammar, the slice spec, the vocabulary map, and the
  conformance direction, plus the parser and emitter rules that keep those
  deterministic. The generated code's own validity stays #1472's contract, gated by
  its requirement that the applied plan passes `protean verify`; the rules here bound
  the input so that gate is reachable, and the generator's tests cover the code it
  emits.

## Alternatives Considered

**Reuse the renderer's Mermaid output as the text format.** The renderer already
emits text, so a model could be Mermaid. Mermaid encodes the diagram's shapes and
edges. It leaves out the fields the generator needs, and it is built to be drawn,
so nothing parses it back. A grammar written for reading carries those fields and
reports a clear line error on a mistake.

**One spec per element type instead of a shared `ElementSpec`.** Separate
`AggregateSpec`, `CommandSpec`, `EventSpec`, and `ProjectionSpec` classes would
name each slot precisely. They would also be four near-identical dataclasses, each
a name and a field list. A shared `ElementSpec` for the four field-carrying
elements keeps the spec small, and the four `SliceSpec` slots already name the
role.

**A flat spec keyed by element, mirroring the IR's dicts.** The IR keys fields by
name in a dict. A dict preserves insertion order in Python, but the serialized
JSON would depend on that order surviving every reader. An ordered list of
`SliceField` makes declaration order explicit in the data, so the generator emits
fields in the model's order without depending on dict-key ordering.

**Round trip through the spec instead of the IR (spec to text to spec).** #1471
could emit text from a hand-built spec and parse it back. That checks the parser
against the emitter, and both are new code that could share the same wrong
assumption. Emitting from the IR checks the grammar against the vocabulary the
renderer already emits, which is the drift the conformance test exists to catch.

**Infer `part_of` and the read side from names.** The parser could attach the
command and event to the aggregate by matching name prefixes, or invent a
projection from the aggregate. A scaffold that infers can produce code the author
did not intend. A one-slice model has one aggregate, so the command and event
attach to it structurally, and the read side is written out or left to the
generator's stated default.
