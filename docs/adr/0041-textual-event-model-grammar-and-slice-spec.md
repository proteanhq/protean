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
  Python identifier that is not a Python keyword. The generator normalizes it the way
  `plan_add_slice` does, through the `_split_words` split `add_plan.py` uses: the
  class name is the PascalCase join and, for an `aggregate`, the `<slug>` is the
  snake_case join, so `order_item`, `orderItem`, and `OrderItem` all name the same
  slice. The class name must be a valid non-keyword identifier for every block. Only
  an `aggregate` derives a slug, and that slug must be a valid non-keyword identifier
  too, so `aggregate Class` is rejected (its slug `class` is a keyword) while
  `command Class` is fine (class `Class`, no slug). The spec stores only the canonical
  class name, so an aggregate name must be slug-recoverable: re-splitting its canonical
  class name yields the same `<slug>`. `OrderItem` recovers `order_item`, but
  `ORDER_ITEM` normalizes to class `ORDERITEM`, whose re-split slug is `orderitem`, so
  it is rejected.
- A **body line** is indented under its header. A blank line and a line whose
  first non-space character is `#` are ignored, so comments and spacing are free.
- A **field line** is `field <name>: <type>` with an optional parenthesized
  constraint list: `field name: string(max_length=100)`. `<name>` is a valid
  Python identifier that is not a Python keyword, read verbatim, because the
  generator writes it as a class attribute. Field names are unique within a block;
  a duplicate is an error. A field name may not start with an underscore (pydantic
  treats an underscore-prefixed attribute as private, so it never becomes a field) or
  use the `model_` prefix, which the grammar reserves because pydantic guards that
  prefix as a protected namespace. It also may not shadow any name
  its block's generated code binds: a member of the generated class, or a fixed local
  the template binds around the fields, such as the aggregate factory's `cls`
  parameter. The `create` factory's other parameters are the fields themselves, so a
  field never clashes with its own parameter, and the normative `name` field is fine. Every field-carrying block is a pydantic `BaseModel` subclass, so the
  member set is the class's full MRO: the template-defined members, the framework base
  (`BaseAggregate`, `BaseMessageType`, or `BaseProjection`), pydantic's `BaseModel`,
  and, for an `aggregate`, the injected `id`. The generator computes this set from the
  base classes and the templates and hands it to the parser, the same way it hands
  over the block-name set below; the parser is a pure function of the model text and
  the sets it is given. The check is the only guard: a field that shadows an inherited
  member does
  not fail `domain.init()`, it warns and registers, then the generated `create`,
  `raise_`, or serialization breaks at use time, so the slice would register yet fail
  `protean verify`. An `aggregate` also reserves `<slug>_id`, the identity reference
  the generator injects, and that generated name must itself be a valid field name: an
  aggregate whose `<slug>_id` trips a field reservation is rejected, so `aggregate
  Model` (whose `model_id` carries the reserved `model_` prefix) is an error. In the
  write-side-only path the event's fields become the
  synthesized projection's fields, so the event's field names are checked against the
  projection's member set too. `<type>` is one of the eight primitive types below, and
  fields keep their declaration order for generation.
- A **field is required and has no default,** except the projection's identity `key`,
  which carries the framework identity default; the grammar does not express other
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
names are unique across the slice on their **canonical** class name, because the
generated command handler and projector import the aggregate, command, event, and
projection by their bare class names, and two spellings normalize to one class:
`aggregate OrderItem` and `command order_item` both become `OrderItem` and collide, so
that model is an error. A `for` or `consumes` reference resolves on the same canonical
name. A block name, and the aggregate's `<slug>`, also may not collide with a symbol
the generated modules bind. The generator computes that set from the project and its
templates and hands it to the parser; it is project-contextual, since the
composition-root variable read from `domain.py` can be any name, so the ADR does not
fix it. A block name is a PascalCase class, so it collides with the PascalCase symbols
a module binds beside a block import: the framework class imports (`Annotated`, `Self`,
`Field`, `BaseAggregate`) and the always-generated derived classes `<Aggregate>Base`
and `<Aggregate>CommandHandler`. The `<slug>` is lowercase, so it collides with the
lowercase bindings: the composition-root variable, the aggregate factory's `cls`
parameter (so an `aggregate Cls` is rejected), and the command handler's `repo` local
and `command` parameter (so an `aggregate Command` is rejected). When the read side is
omitted, the generator synthesizes `<Aggregate>Summary` and `<Aggregate>Projector`,
which then must not collide with the declared blocks; a model that declares its own
projection and projector names them from the spec, so the normative full model is
fine.

The parse is deterministic and infers nothing. Field names are preserved as written;
a block name is normalized to its canonical class name and slug (above). A
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

Every generated field is required (the projection `key` aside) and unbounded unless
it declares `max_length`, and the generator chooses a declaration form that reaches
that. `string` uses a bare `str` annotation and `string(max_length=N)` an
`Annotated[str, Field(max_length=N)]`; `integer`, `float`, `boolean`, `date`, and
`datetime` use their bare annotation (`int`, `float`, `bool`, `date`, `datetime`),
each required with no extra keys; `text` uses `Text(sanitize=False, required=True)`,
`text(max_length=N)` a `Text(max_length=N, sanitize=False, required=True)`, and a
non-key `identifier` an `Identifier(sanitize=False, required=True)`, all factory forms,
since no bare annotation yields those IR types. The generator writes `sanitize=False`
on the factory forms, so the generated declaration disables sanitization; the IR
records a `sanitize` key only when it is true, so these forms carry none. Protean's required-string rule adds an implicit `min_length=1` to a
required `Text` or `Identifier` factory field, so a `text` field and a required
non-key `identifier` are non-empty. That `1` is the implied form of a required field
of those two types, so it round-trips even though the grammar has no syntax for it
(both the source and the generated field carry it), and the emitter treats it as part
of the required semantics and does not count as a third constraint. The bare-annotation forms (`string`
and the numeric and temporal types) carry no `min_length`. An IR field is not
representable, and the emitter rejects its cluster, when it carries anything else the
grammar cannot say: a `sanitize` flag, a `min_length` on a `string` (a
`String(required=True)` source field carries a `min_length=1` the grammar's `string`
cannot express), a `max_length` on a field that is not `string` or `text` (Protean
keeps `max_length` on any string-based field, so an `Identifier(max_length=100)`
carries one the grammar's `identifier` cannot express), a numeric `min_value` or
`max_value`, a `choices` or `unique` marker, or an author `default`.

The auto-generated `id` an aggregate carries (IR kind `auto`, type `Auto`) is not
a grammar type. The framework injects it, no one writes it, so the grammar does
not carry it and the emitter skips it. The grammar supports only an aggregate whose
identity is that injected id, which the emitter detects by `auto_generated: true` on
the identity field. An aggregate whose identity field lacks that flag is outside the
grammar, and the emitter rejects that cluster, since serializing the identifier as an
ordinary field would let the generator inject a fresh auto id and change the identity.
Neither the name nor the kind alone is the test: an explicit `id =
Identifier(identifier=True)` keeps the name `id` but is `kind identifier`, and an
authored `Auto(identifier=True)` is `kind auto` yet carries no `auto_generated` flag,
so both are authored identities the emitter rejects; only `auto_generated: true` marks
the injected id.

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
package `__init__.py`, the aggregate's injected identity, and the projection's
`Meta.stream_name` (the aggregate `<slug>`), which the spec does not store because it
is derived. It wires fields by
name: the command handler creates the aggregate from the command's fields, the
aggregate raises the event with its identity and its same-named fields, and the
projector copies each projection field from the event field of the same name. The
aggregate's identity travels as a field named `<slug>_id`: the generated `create`
raises the event with `<slug>_id` set to the aggregate's `id`, and the projection's
`key` is that same `<slug>_id`. v1 targets the default identity (`identity_type =
string`, `identity_strategy = uuid`); a project configured for `integer` or `uuid`
identity, or a non-uuid strategy (ADR-0021), is out of scope. The aggregate id is then
a UUID stored as a string, so `<slug>_id` is an unconstrained `string` or
`identifier`, with no `max_length`. The command declares the aggregate's
authored fields, the event declares those fields plus `<slug>_id`, and the projection
declares `<slug>_id` and a subset of the event's fields. The identity `<slug>_id` is
the one field allowed to differ across blocks: the event's `<slug>_id` is an
unconstrained `string` or non-key `identifier`, and the projection's is the
`identifier` `key` (the projection identity is always the `identifier` key, since
`key` is valid only on a projection `identifier`). Every other field shared by name carries the same type and
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
| `field <n>: <t>` under an element | `<element>.fields[]` | `<element>.fields[<name>]` (a name-keyed dict) | (fields are not drawn; the diff reports `field <n>`) |
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
managers, the hexagon nodes), and it does not cover framework-made events: a **fact
event** (`is_fact_event`), which the renderer already filters, or any other event
carrying the `auto_generated` flag, which the emitter also skips. A one-slice model is
a command,
an aggregate, an event, and an optional read model. Automations and multi-slice
models are a later grammar.

### Conformance: IR to text to spec

The grammar stays aligned with the renderer's vocabulary through a structural
round trip, run as a build-time test, with no live sync between the two.

#1471 adds an **emitter** that reads the IR (the same dict the renderer reads) and
one cluster, and produces grammar text for that slice. The emitter emits only what
the vocabulary map covers: the aggregate and its authored fields, the command, the
non-fact event, and the read model's projection and projector with the event it
consumes. To judge eligibility it also reads IR the map does not cover, and emits none
of it: the identity field's `auto_generated` flag, the aggregate's
`options.stream_category`, the domain's `identity_type` and `identity_strategy`, and
the projector's `aggregates`, `stream_categories`, and `subscription`. These are
eligibility-only inputs. It renders every name by its short form, the same `short_name` the
renderer applies: `projector_for` is stored as a full projection FQN, and the
emitter shortens it to the class name the `for` line carries. It recovers the
`consumes` name by matching the projector's `handlers` key back to the slice's
event. Because the parser canonicalizes names, the emitter requires each
participant's short name to already be canonical (its `_split_words` PascalCase form);
a source class whose name is not canonical, such as `order_item`, makes the cluster
ineligible, since emitting it verbatim would parse back to a different name. It skips
the injected `id`, element options, and every element the grammar does not carry
(entities, value objects, repositories, database models, command handlers,
application services, queries, automations, fact events).

The conformance compares only the **vocabulary-covered data**: the participants'
names, their authored fields, and the wiring (`for`, `consumes`). Everything else is
skipped from the comparison and is not emitted: a canonical slice's command handler,
the injected `id`, element options, and message metadata (an event's `__version__`,
its publication or deprecation options). Not being compared is not the same as not
being read. The eligibility rule still reads a few options, such as the aggregate's
`stream_category`, and rejects a non-default value, so a cluster with a custom stream
category is ineligible even though that option is never emitted.

Within that covered data the emitter's precondition is one rule over what the IR
shows: it emits a cluster only when the emitted grammar text would parse back to a
spec whose covered data matches the cluster, judged against the parser rules the IR
can decide. So the cluster must satisfy the cross-block field-set and identity rules
and the per-field shape: exactly one command and one authored event, where authored
means `is_fact_event` false and no `auto_generated` flag (an `auto_generated` event is
framework-made, and the grammar's `event` is authored); the field-set equality (command equals aggregate, event equals aggregate plus `<slug>_id`,
projection equals `<slug>_id` plus a subset of the event); an aggregate whose identity
field is the injected id (`auto_generated: true`); either no read side or one
projection with exactly one field marked `key` (`identifier: true`), alongside any
non-key fields, and one projector; a projector whose `handlers`
route only that event, whose `aggregates` are exactly the slice's aggregate, whose
`stream_categories` equal the aggregate's class-derived default
(`<domain normalized_name>::<underscored aggregate name>`), and whose `subscription`
is the framework default `{config: {}, profile: null, type: null}` (the value the IR
carries for an unconfigured projector); distinct canonical short names; and every
authored field within the eight types and two constraints, required and without an
author default (the injected `id`, `kind auto`, is skipped and exempt), save the
implicit `min_length=1` a required `text` or `identifier` carries,
which is part of the required semantics; the projection's identity `key` is the one
optional field, an `identifier` carrying no `required` flag.

The project-contextual reserved-name and slug-collision rules are the generator's to
enforce at generation time, when it holds the project's composition root and
templates. They read the `domain.py` root variable, which the IR does not carry, so
the emitter cannot re-check them, and the conformance corpus is built from clusters
that already satisfy them.

A covered participant that carries data the grammar cannot represent makes the cluster
ineligible: a field whose IR `type` is outside the eight (`Status`, a `List` or `Dict`
container), a constraint or flag with no grammar syntax (a `sanitize` flag, a numeric
`min_value` or `max_value`, a stray `min_length`, a `choices` or `unique` marker, an
optional or defaulted field), an extra or mismatched field, a second projection or
projector, a projector wired to another aggregate's events, wired via
`stream_categories` with an empty `aggregates`, or with a `subscription` other than
that default, an aggregate whose `stream_category` differs from its class-derived
default, an aggregate
whose identity field is not the injected id (no `auto_generated: true`, including an
authored `Auto(identifier=True)`), a projection with more than one `identifier: true`
field, a domain `identity_type` other than the default `string` (a `uuid` type keeps
native-UUID storage per ADR-0021, which the spec cannot carry, so it is not the
default `string` and is out), or an `identity_strategy` other than the default `uuid`
(the injected id is `kind auto` for every strategy and type, so the domain identity
config is the only signal), or a field name that trips a reservation the emitter can
derive from the IR and the base classes: a keyword, an underscore or `model_` prefix,
or a generated-class member. The project-contextual block-name and slug collisions are
the generator's to enforce at generation time, since the composition-root variable is
not in the IR, so the emitter does not re-check them. The emitter judges a field on its IR `type`, so a Python type the builder
already collapsed to a grammar type carries as that type: `IRBuilder._resolve_type_name`
falls back to `String` for an unmapped type such as `decimal.Decimal`, so that field
is `String` in the IR and round-trips as grammar `string`. That collapse is the
builder's, before the emitter, and outside this round trip. The emitter raises on an
ineligible cluster, so it never drops or distorts a participant the vocabulary map
covers, and conformance cannot pass while the emitter loses a covered participant.

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
Order slice above. It parses to this spec, shown below with object keys in reading
order. The serializer sorts object keys the ADR-0033 way, so a byte-level fixture
sorts them, while the `fields` list keeps its declaration order:

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
