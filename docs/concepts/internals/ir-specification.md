# Intermediate Representation (IR)

The Protean IR captures the **topology** of a domain model — what elements
exist, what shape they have, and how they connect — in a portable JSON format.
It is the machine-readable representation of everything a `Domain` knows after
`domain.init()` completes.

The IR answers three kinds of questions:

- **Structural**: What aggregates exist? What entities, value objects, fields,
  and constraints do they contain?
- **Behavioral**: What commands target which aggregates? What events do they
  raise? What handlers process those commands and events?
- **Infrastructure**: What repositories persist which aggregates? What database
  models map them?

The IR never captures **logic** — what happens inside method bodies, how
invariants are evaluated, or what transformations handlers perform.

---

## Philosophy & Principles

**Topology, not logic.**
The IR captures *what* and *how connected*, never *what happens inside*.
When the IR says an aggregate has a post-invariant named
`order_must_have_items`, it records the fact that this guard exists and when it
runs — not what it checks.

**Declare, don't detect.**
When the IR needs information not naturally introspectable (like whether an
event is published), the solution is explicit developer declaration via `Meta`
options — never static analysis of Python source.

**Aggregate-centric, flow-aware.**
The primary organization mirrors DDD's aggregate cluster concept. Cross-cutting
concerns (domain services, process managers, subscribers) get explicit treatment
in a separate section.

**Deterministic and diffable.**
The same domain model always produces byte-identical IR JSON. This is
non-negotiable for git diffing, compatibility checking, and staleness detection.

**One document, one bounded context.**
A single IR document represents one `Domain` instance = one bounded context.
Multiple aggregates within one bounded context is normal DDD — `Order` and
`Payment` aggregates in the same domain are clusters within one BC.

**Lossless within scope.**
Every piece of structural and behavioral metadata available on the composite
root after `domain.init()` is capturable in the IR. Downstream tools never need
to go back to Python source for information they need.

**Uniform over special-cased.**
Every element carries an `element_type` discriminator. Handler wiring always
uses lists (even for 1:1 cardinality). This makes generic IR processing
possible without type-specific code paths.

**Open for extension.**
Every object in the IR can carry additional keys in future versions. Consumers
MUST ignore keys they don't recognize.

---

## Compatibility Contract

### Versioning

The `ir_version` field uses semantic versioning (`MAJOR.MINOR.PATCH`):

- **Patch** (0.1.0 → 0.1.1): Bug fixes in IR generation. No schema changes.
- **Minor** (0.1.0 → 0.2.0): Additive changes only. New optional keys, new
  sections, new element types. **Consumers of 0.1.0 can read 0.2.0 by ignoring
  unknown keys.**
- **Major** (0.x → 1.0): Breaking changes. Keys may be removed, renamed, or
  change meaning.

### Consumer Rules

1. **MUST ignore unknown keys** at every level.
2. **MUST NOT rely on key ordering** for semantics.
3. **SHOULD provide defaults** for missing optional keys.
4. **MUST check `ir_version`** and reject documents with a higher major version.

### Producer Rules

1. **MUST NOT remove or rename** existing keys in minor versions.
2. **MAY add new keys**, top-level sections, or element type values in minor
   versions.
3. **MUST include `ir_version`** in every document.

---

## Top-Level Structure

```json
{
  "$schema": "https://protean.dev/ir/v0.1.0/schema.json",
  "ir_version": "0.1.0",
  "generated_at": "2026-03-01T12:00:00Z",
  "checksum": "sha256:a1b2c3...",

  "domain": { },
  "contracts": { },
  "clusters": { },
  "projections": { },
  "flows": { },
  "elements": { },
  "diagnostics": [ ]
}
```

| Section | Purpose | Maps to |
|---------|---------|---------|
| `domain` | Bounded context identity and global config | `Domain.__init__()` and `Config2` |
| `clusters` | Aggregate clusters: elements within each aggregate boundary | `_assign_aggregate_clusters()` output |
| `projections` | Read side (CQRS): projections, projectors, queries | Cross-aggregate — not tied to one cluster |
| `flows` | Cross-aggregate coordination: domain services, PMs, subscribers | Elements spanning 2+ aggregates |
| `contracts` | Published language: events available to other BCs | Derived from `published` annotations |
| `elements` | Flat index by element type for O(1) lookup | Derived from all sections |
| `diagnostics` | Builder warnings and errors | Informational — IR is valid regardless |

### Top-Level Metadata

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `$schema` | string | yes | URI to the IR JSON Schema |
| `ir_version` | string | yes | Semantic version of the IR format |
| `generated_at` | string | yes | ISO 8601 UTC timestamp |
| `checksum` | string | yes | `sha256:` prefixed hex digest |
| `contracts` | object | no | Omitted when no published events |
| `diagnostics` | list | yes | May be empty `[]` |

### Checksum Algorithm

1. Build the complete IR dict
2. Remove the `generated_at` and `checksum` keys
3. Serialize to **canonical JSON**: sorted keys, no indent, separators
   `(',', ':')` (compact, no whitespace)
4. Encode to UTF-8 bytes
5. Compute SHA-256
6. Format as `"sha256:<hex_digest>"`

---

## Domain Metadata

The `domain` section captures bounded context identity and global configuration.

```json
{
  "domain": {
    "name": "Ordering",
    "normalized_name": "ordering",
    "camel_case_name": "Ordering",
    "identity_strategy": "uuid",
    "identity_type": "string",
    "event_processing": "async",
    "command_processing": "async"
  }
}
```

| Field | Source | Description |
|-------|--------|-------------|
| `name` | `domain.name` | Display name |
| `normalized_name` | `domain.normalized_name` | Lowercase form for stream prefixes |
| `camel_case_name` | `domain.camel_case_name` | CamelCase form for `__type__` strings |
| `identity_strategy` | Config | `"uuid"`, `"function"`, or `"database"` |
| `identity_type` | Config | `"string"` or `"integer"` |
| `event_processing` | Config | `"sync"` or `"async"` |
| `command_processing` | Config | `"sync"` or `"async"` |

Database connection strings, broker URLs, and other deployment-specific settings
are excluded. The IR captures structural identity, not deployment topology.

---

## Aggregate Clusters

The `clusters` section is the heart of the IR. Each key is an aggregate's FQN,
and the value contains the complete cluster.

### Cluster Structure

```json
{
  "clusters": {
    "<aggregate_fqn>": {
      "aggregate": { },
      "entities": { },
      "value_objects": { },
      "commands": { },
      "events": { },
      "command_handlers": { },
      "event_handlers": { },
      "application_services": { },
      "repositories": { },
      "database_models": { }
    }
  }
}
```

An element belongs to a cluster when its `meta_.aggregate_cluster` points to
the cluster's root aggregate. Empty sub-sections are included with `{}` to
make the structure predictable.

### Common Element Shape

Every element carries a consistent set of base attributes:

```json
{
  "fqn": "ecommerce.ordering.Order",
  "name": "Order",
  "module": "ecommerce.ordering",
  "element_type": "AGGREGATE",
  "description": "Root aggregate for customer orders.",
  "auto_generated": false
}
```

| Attribute | Type | Required | Description |
|-----------|------|----------|-------------|
| `fqn` | string | yes | Fully qualified name — the stable identifier |
| `name` | string | yes | Short class name |
| `module` | string | yes | Python module path |
| `element_type` | string | yes | `DomainObjects` enum value |
| `description` | string | no | From class docstring. Omitted if none |
| `auto_generated` | bool | no | `true` for framework-generated elements. Omitted (defaults to `false`) for user-declared elements |

### Aggregate

The aggregate element includes options, identity, fields, invariants, and
(for event-sourced aggregates) apply handlers.

**Options reference (v0.1.0):**

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `is_event_sourced` | bool | `false` | Uses event sourcing |
| `fact_events` | bool | `false` | Auto-generate fact events on persistence |
| `provider` | string | `"default"` | Database provider name |
| `schema_name` | string | underscore(class_name) | Storage table/collection name |
| `stream_category` | string | `{normalized_name}::{underscore(class_name)}` | Event stream prefix |
| `auto_add_id_field` | bool | `true` | Auto-inject an `id` field |
| `limit` | int | `100` | Default query result limit |

**Invariants** are grouped by stage, always fully present:

```json
"invariants": {
  "pre": ["validate_order_not_cancelled"],
  "post": ["total_must_be_positive"]
}
```

**Apply handlers** (event-sourced only) map event FQN to method name:

```json
"apply_handlers": {
  "banking.accounts.AccountOpened": "on_account_opened",
  "banking.accounts.DepositMade": "on_deposit_made"
}
```

### Entity

Entities carry `part_of` (FQN of parent aggregate or entity), their own
`identity_field`, `fields`, `invariants`, and `options`. Auto-injected
`Reference` fields appear as regular fields with `"kind": "reference"`.

### Value Object

Value objects carry `part_of` (may be `null` for standalone VOs), `fields`, and
`invariants`. They cannot have `identifier`, `unique`, `HasOne`, `HasMany`, or
`Reference` fields.

### Command

Commands carry `__type__` (message routing string:
`{Domain}.{ClassName}.{version}`), `__version__`, `part_of`, and `fields`.
Commands are immutable data — no invariants, no identity field. Commands are
always internal to the bounded context.

### Event

Events additionally carry `is_fact_event` and `published` flags:

- `is_fact_event`: `true` for auto-generated fact events
- `published`: `true` if part of the BC's published language (defaults to
  `false`, omitted per sparse representation)

When an aggregate has `fact_events: true`, the framework auto-generates a
fact event class that appears in the cluster's `events` section with both
`is_fact_event: true` and `auto_generated: true`.

### Command Handler

Command handlers include a `handlers` map (`__type__` → list of method names),
`stream_category`, and a `subscription` block.

### Event Handler

Event handlers include a `handlers` map, an optional `source_stream` for origin
filtering, `stream_category`, and a `subscription` block. The `$any` wildcard
key means the handler processes all events on its stream.

### Other Cluster Elements

`application_services`, `repositories`, and `database_models` carry base
attributes plus `part_of`. Database models additionally carry `database` and
`schema_name`.

---

## Field Representation

Fields use a uniform schema with `kind` as the discriminator. Three design
rules govern field representation:

1. **Flat structure.** All attributes are top-level keys. No nesting.
2. **Sparse representation.** Only non-default, meaningful attributes are
   present. A field without `max_length` does not include `"max_length": null`.
3. **Extensible.** Future field attributes can be added in minor versions.

### Field Kinds

| `kind` | Source | Description |
|--------|--------|-------------|
| `"standard"` | `String`, `Integer`, `Float`, `Boolean`, `Date`, `DateTime` | Basic data field |
| `"text"` | `Text` | Unbounded text |
| `"identifier"` | `Identifier` | Identity-capable field |
| `"auto"` | `Auto` | Auto-generated identity |
| `"list"` | `List` | Typed list container |
| `"dict"` | `Dict` | Dictionary container |
| `"value_object"` | `ValueObject(SomeVO)` | Embedded value object |
| `"value_object_list"` | `ValueObjectList(SomeVO)` | List of embedded VOs |
| `"has_one"` | `HasOne(SomeEntity)` | 1:1 child association |
| `"has_many"` | `HasMany(SomeEntity)` | 1:N child association |
| `"reference"` | `Reference(SomeAggregate)` | Back-reference to parent |

### Field Attributes

All possible keys (no single field has all of them):

| Attribute | Description |
|-----------|-------------|
| `kind` | Field kind discriminator (always present) |
| `type` | Protean type name (present on data fields, omitted on associations) |
| `required` | Must have a value after construction |
| `identifier` | Marks the identity field |
| `unique` | Uniqueness constraint |
| `default` | Default value (see serialization rules below) |
| `description` | Human-readable description |
| `max_length`, `min_length` | String length constraints |
| `max_value`, `min_value` | Numeric bounds |
| `choices` | Sorted list of allowed values |
| `sanitize` | Whether the field value is sanitized |
| `increment` | Auto-increment flag |
| `content_type` | Element type of a container (`List`, `ValueObjectList`) |
| `auto_generated` | `true` for framework-injected fields |
| `target` | FQN of the associated element (associations) |
| `via` | FK field name on the child entity |
| `linked_attribute` | Identity field on the reference target |

### Default Value Serialization

| Scenario | IR Representation |
|----------|-------------------|
| Immutable literal | JSON value: `"PENDING"`, `0`, `false` |
| `None` as explicit default | `"default": null` |
| No default specified | Key omitted |
| Callable (`datetime.now`) | `"default": "<callable>"` |

### Type Names

Data fields use Protean type names: `String`, `Text`, `Integer`, `Float`,
`Boolean`, `Date`, `DateTime`, `Identifier`, `Auto`, `List`, `Dict`.
Association fields omit `type` — the `target` FQN provides type information.

---

## Handler Wiring

### Uniform Handler Format

All handler method values are **lists**, even when cardinality is 1:1. The
domain constraint (e.g., commands must have exactly one handler) is enforced by
the framework, not the IR shape.

```json
{
  "handlers": {
    "<__type__ string>": ["method_name"],
    "$any": ["wildcard_method"]
  }
}
```

**One exception:** `apply_handlers` on event-sourced aggregates use event
**FQN** as keys and single strings as values (not lists), since each event maps
to exactly one `@apply` method.

### Subscription Block

Present on command handlers, event handlers, projectors, and process managers:

```json
{
  "subscription": {
    "type": "stream",
    "profile": "production",
    "config": {}
  }
}
```

| Key | Values | Description |
|-----|--------|-------------|
| `type` | `"stream"`, `"event_store"`, `null` | Subscription mechanism. `null` = framework default |
| `profile` | `"production"`, `"fast"`, `"batch"`, `"debug"`, `"projection"`, `null` | Configuration preset. `null` = framework default |
| `config` | dict | Handler-specific overrides. Empty `{}` = no overrides |

The subscription block is always fully present. Unlike sparse field attributes,
`null` here means "use framework defaults" — a semantically meaningful value.

### Process Manager Handler Map

Process managers extend the handler format with lifecycle metadata:

```json
{
  "handlers": {
    "Ordering.OrderPlaced.v1": {
      "methods": ["on_order_placed"],
      "start": true,
      "end": false,
      "correlate": "order_id"
    }
  }
}
```

| Attribute | Description |
|-----------|-------------|
| `methods` | Handler method names |
| `start` | Whether this handler initiates a new process instance |
| `end` | Whether this handler completes the process |
| `correlate` | String (same-name mapping) or dict (`{"pm_field": "event_field"}`) |

### Command→Event Causality

The IR does not capture per-command event causality. Events are raised within
aggregate methods, and handler logic is conditional — a static declaration
cannot capture this. Consumers can reconstruct the flow graph by combining
command→handler, handler→aggregate, aggregate→events, and event→handler
mappings.

---

## Projections & Read Side

Projections live outside `clusters` because they may combine data from multiple
aggregate streams.

```json
{
  "projections": {
    "<projection_fqn>": {
      "projection": { },
      "projectors": { },
      "queries": { },
      "query_handlers": { }
    }
  }
}
```

**Projection** elements include `options` (provider, cache, schema_name,
order_by, limit), `identity_field`, and `fields`.

**Projectors** specify `projector_for` (FQN), `aggregates` (sorted list of
aggregate FQNs), `stream_categories`, `subscription`, and `handlers`.

**Queries** carry `__type__` but **not** `__version__` — queries are local
read-side operations, not cross-context messages. Format:
`{Domain}.{ClassName}`.

**Query handlers** have standard handler maps keyed by query `__type__`.

---

## Cross-Cutting Flows

The `flows` section captures elements spanning aggregate boundaries.

### Domain Services

Domain services have `part_of` as a sorted list of 2+ aggregate FQNs and carry
`invariants`.

### Process Managers

Process managers are stateful, event-driven coordinators. They include:

- `identity_field` and `fields` (persistent state)
- `stream_categories` (what they subscribe to)
- `handlers` with lifecycle metadata (`start`, `end`, `correlate`)
- `transition_event` (auto-generated event: `fqn` and `__type__` only)

### Subscribers

Subscribers consume messages from external brokers. They carry `broker` and
`stream` — minimal metadata reflecting the framework's simple
`__call__(payload: dict)` entry point.

---

## Contracts (Published Language)

The `contracts` section summarizes the bounded context's published events:

```json
{
  "contracts": {
    "events": [
      {
        "__type__": "Ordering.OrderPlaced.v1",
        "fqn": "ecommerce.ordering.OrderPlaced"
      }
    ]
  }
}
```

- Events are sorted by `__type__`
- Only events can be published; commands are always internal
- The section is derived — it contains no information not in the clusters
- It may be omitted when the domain has no published events

---

## Elements Index

A flat lookup table mapping element types to sorted FQN lists:

```json
{
  "elements": {
    "AGGREGATE": ["ecommerce.ordering.Order"],
    "COMMAND": ["ecommerce.ordering.PlaceOrder"],
    "EVENT": ["ecommerce.ordering.OrderPlaced"],
    ...
  }
}
```

- Keys are `DomainObjects` enum values (uppercase)
- Empty lists are included for types with no instances
- Spans all sections (clusters, projections, flows)
- Derived, not canonical — sections are the source of truth

---

## Identifiers

### Fully Qualified Name (FQN)

Every element is identified by `cls.__module__ + "." + cls.__qualname__`.
FQNs are deterministic, human-readable, and match the registry lookup key.

### Message Type String (`__type__`)

Commands and events carry `{domain.camel_case_name}.{class_name}.{version}`
for message routing. FQN is structural identity; `__type__` is behavioral
identity. They serve different purposes and evolve independently.

All cross-references (e.g., `part_of`, `target`) use FQNs. Handler maps use
`__type__` strings as keys. Apply handlers use FQNs.

---

## Determinism Guarantees

### Key Ordering

All dictionary keys are sorted alphabetically at every level: top-level
sections, elements within sections, fields, handler maps, options, and field
attributes.

### List Ordering

All lists are sorted: FQNs alphabetically, `choices` alphabetically, handler
method names alphabetically, contracts by `__type__`.

### Value Normalization

- Strings preserve declared case
- Numbers use standard JSON formatting; floats and integers are distinct
  (`0.0` vs `0`)
- Optional attributes with null/default values are omitted (sparse)
- Empty dicts `{}` are included for empty cluster sub-sections
- Empty lists `[]` are included in the elements index
- `invariants` blocks always include both `pre` and `post` keys

### Excluded from Determinism

- `generated_at`: always differs
- `checksum`: derived from content (excluded from its own computation)

---

## Extension Points

**New top-level sections** can be added in minor versions. Existing consumers
ignore them.

**New element types** get an `element_type` discriminator and are placed in the
appropriate section.

**New attributes** on existing elements are added as optional keys.

**New field kinds** (e.g., `"json"`, `"encrypted"`) can be introduced.
Consumers that don't recognize a kind treat the field as opaque metadata.

**State machines** (future): Fields with `choices` implicitly define state
vocabulary. A future version may add explicit transition declarations.

**Evolution tracking** (future): Event version transitions and upcaster chain
metadata.

---

## Diagnostics

```json
{
  "diagnostics": [
    {
      "code": "UNHANDLED_EVENT",
      "element": "banking.accounts.AccountClosed",
      "level": "warning",
      "message": "Event AccountClosed has no registered handler"
    }
  ]
}
```

| Field | Type | Description |
|-------|------|-------------|
| `code` | string | Machine-readable identifier |
| `element` | string | FQN of the related element |
| `level` | string | `"error"`, `"warning"`, or `"info"` |
| `message` | string | Human-readable description |

Diagnostics are included in checksum computation (same domain = same
diagnostics). They do not affect IR validity — an IR with error-level
diagnostics is still a valid document.

---

## Design Decisions

### What the IR Does Not Capture

- Method implementations and handler bodies
- Runtime state (aggregate instances, event store positions)
- Adapter internals (connection strings, query implementations)
- Python AST or source code
- Element inheritance (Protean elements are flat, matched by `__type__`)
- Aggregate business methods (not in framework metadata)
- Custom Meta options (framework uses a predefined set only)

### Key Trade-offs

**FQN refactoring fragility.**
FQNs change when code is moved. Commands and events have the refactor-proof
`__type__` string for behavioral identity. A future version may introduce
`canonical_id` for structural elements.

**Subscriber thinness.**
Subscribers capture only `broker` and `stream`. Visualization tools cannot
draw data flow edges through subscribers because internal dispatching is logic.
A future version may add `dispatches` declarations.

**Enum class reference lost.**
When `choices` come from a Python Enum, the IR captures only the values.
Protean's field resolution discards the class reference.

**Callable defaults.**
Callables are not JSON-serializable. The sentinel `"<callable>"` indicates a
default exists without revealing what it produces.

**Float serialization.**
Python's `json.dumps()` is the reference serializer. `0.0` serializes as
`0.0` (not `0`), preserving type distinction across Python 3.11+.

### Value Objects Across Aggregates

A VO declared `part_of=Order` appears in the Order cluster, even if Payment
also references it. The Payment field references the VO by FQN — cross-cluster
references are valid. Standalone VOs (`part_of=None`) appear only in the
elements index.

### Diagnostics in Checksum

Diagnostics are deterministic (same domain = same diagnostics) and included in
the checksum. Upgrading Protean may introduce new diagnostic rules, changing the
checksum. The expected workflow: upgrade → regenerate IR → review diff → commit.

---

## JSON Schema

The complete JSON Schema (Draft 2020-12) for IR v0.1.0 is available at:

- **In the package**: `protean.ir.SCHEMA_PATH`
  (`src/protean/ir/schema/v0.1.0/schema.json`)
- **Canonical URL**: `https://protean.dev/ir/v0.1.0/schema.json`

### Reference Examples

Two reference IR documents are included in the package at
`protean.ir.EXAMPLES_DIR`:

- **Fidelis** (`fidelis-ir.json`): A banking domain with an event-sourced
  `Account` aggregate, demonstrating apply handlers, compliance event handlers,
  and a diagnostic warning for an unhandled event.

- **Ordering** (`ordering-ir.json`): An e-commerce domain with two aggregates
  (`Order` and `Payment`), demonstrating entities, value objects, fact events,
  a cross-aggregate process manager, projections with queries, and an external
  subscriber.
