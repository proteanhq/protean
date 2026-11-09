# `protean schema`

The `protean schema` command group generates and inspects JSON Schema
(Draft 2020-12) documents for data-carrying domain elements: aggregates,
entities, value objects, commands, events, and projections.

All commands accept either `--domain` (live domain module) or `--ir`
(serialized IR file) as input.

## Commands

| Command | Description |
|---------|-------------|
| `protean schema generate` | Generate JSON Schema files for all data-carrying elements |
| `protean schema show` | Display the JSON Schema for a specific element |
| `protean schema render` | Render index DDL artifacts (with `--indexes`) |

---

## `protean schema generate`

Generates JSON Schema files for every data-carrying element in the domain
and writes them to the output directory.

```bash
# From a live domain
protean schema generate --domain=my_app.domain

# From a serialized IR file
protean schema generate --ir=domain-ir.json

# Custom output directory
protean schema generate --domain=my_app.domain --output=build
```

**Options**

| Option | Description | Default |
|--------|-------------|---------|
| `--domain`, `-d` | Path to the domain module (e.g. `my_app.domain`) | |
| `--ir` | Path to an IR JSON file | |
| `--output`, `-o` | Root output directory | `.protean` |
| `--format`, `-f` | Output format: `json`, `avro`, `protobuf`, or `all` | `json` |

Either `--domain` or `--ir` is required; they are mutually exclusive.

**Formats.** `--format avro` emits Avro `{name}.v{version}.avsc` records (null-first
unions for optionals, so optional fields default to `null`;
`date`/`timestamp-millis` logical types, `Identifier` fields as a plain
`string`, and the `decimal` logical type for a `Decimal` field that sets a
positive `precision` no smaller than its `scale`; nested value objects become
named records referenced by fullname). `--format protobuf` emits proto3
`{name}.v{version}.proto` messages with `optional`/`repeated` labels,
`.google.protobuf.Timestamp` for dates, and `string` for a `Decimal` field.
Protean assigns field numbers deterministically in sorted field-name order, so
re-generating an *unchanged* schema is byte-identical. Adding or removing a
field can move the numbers of the fields that sort after it. Renaming a field
can move its own number and the numbers of the fields between its old and new
name. Within one `__version__`, `protean ir diff` reports a change that moves an
event's own field number as breaking (`field_number_changed`). It does not
check fact events, the nested messages of value objects an event holds, or
other elements, so their numbers can move when their fields change. The Avro
and Protobuf formats are compiler backends
for schema *emission*, and runtime binary encode/decode is out of scope.
Protean does not carry field-level constraints (choices/enums, min/max) into
either format.

**Protobuf imports.** Each value object and entity is defined once, in its own
file. A file that uses one imports that file by its path under `schemas/` and
names the type by its full name with a leading dot, such as
`.shared.kernel.Money`. The leading dot tells `protoc` to resolve the name from
the root package. Compile the files with `-I <output>/schemas`, for example
`protoc -I .protean/schemas --descriptor_set_out=out.pb $(find .protean/schemas -name '*.proto')`.
Two cases are defined as a nested message inside the file that uses them,
instead of being imported:

- A value object that belongs to no aggregate cluster, such as one with no
  `part_of` that only projections use, gets no file of its own.
- Entities that refer to each other through `HasOne` or `HasMany` would import
  each other in a cycle, which `protoc` rejects.

The command fails with an error when two elements would be written to the same
file, for example two value objects with the same class name in one cluster.

`--format all` emits every format into one `schemas/` tree in a single pass.
Each element gets its JSON, Avro, and Protobuf files with distinct extensions,
so no format overwrites another. Together with
[`protean events catalog`](data/events.md), `--format all` is the first step
toward a local schema registry.

**Output structure**

Schemas are written to `<output>/schemas/`, grouped by aggregate cluster:

```
.protean/
├── ir.json
└── schemas/
    ├── Order/
    │   ├── aggregates/
    │   │   └── Order.v1.json
    │   ├── commands/
    │   │   └── PlaceOrder.v1.json
    │   ├── entities/
    │   │   └── LineItem.v1.json
    │   ├── events/
    │   │   └── OrderPlaced.v2.json
    │   └── value_objects/
    │       └── Money.v1.json
    └── projections/
        └── OrderDashboard.v1.json
```

Filenames include the element version for events and commands. Other elements
default to `v1`. The `schemas/` directory is cleared on each run to remove
stale files.

The `ir.json` written alongside the schemas is a canonical baseline,
byte-identical to `protean ir show --canonical`. It omits the volatile
`generated_at` timestamp, so a committed `.protean/ir.json` only changes when
the domain contract changes.

---

## `protean schema show`

Displays the JSON Schema for a single element, looked up by short name or
fully qualified name (FQN).

```bash
# By short name
protean schema show OrderPlaced --domain=my_app.domain

# By FQN
protean schema show my_app.ordering.OrderPlaced --domain=my_app.domain

# Raw JSON (for piping)
protean schema show OrderPlaced --domain=my_app.domain --raw

# From an IR file
protean schema show OrderPlaced --ir=domain-ir.json --raw
```

With `--raw`, the JSON is written to stdout while logs go to stderr, so the
output is safe to pipe (`protean schema show ... --raw | jq`).

**Options**

| Option | Description | Default |
|--------|-------------|---------|
| `--domain`, `-d` | Path to the domain module | |
| `--ir` | Path to an IR JSON file | |
| `--raw` | Output plain JSON without syntax highlighting | `false` |

**Arguments**

| Argument | Description |
|----------|-------------|
| `element` | Element short name (e.g. `OrderPlaced`) or FQN (e.g. `app.OrderPlaced`) |

**Disambiguation**

If multiple elements share the same short name, the command lists all matching
FQNs and asks you to use the full FQN:

```
Multiple elements match 'Order':
  ecommerce.ordering.Order
  ecommerce.shipping.Order

Use the full FQN to disambiguate.
```

---

## `protean schema render`

Renders the index declarations on a domain's aggregates and entities to
per-dialect `CREATE INDEX` DDL files. It never executes DDL. It writes `.sql`
artifacts for review or for application through your own migration tooling.

```bash
# Render index DDL for the default dialects
protean schema render --indexes --domain=my_app.domain

# Restrict to specific dialects
protean schema render --indexes --domain=my_app.domain --dialects=postgresql,sqlite

# Custom output directory
protean schema render --indexes --domain=my_app.domain --output=build
```

**Options**

| Option | Description | Default |
|--------|-------------|---------|
| `--indexes` | Render index DDL (required; nothing is applied without it) | `false` |
| `--domain`, `-d` | Path to the domain module (e.g. `my_app.domain`) | |
| `--dialects` | Comma-separated dialects to render (`postgresql`, `sqlite`, `mssql`, `mysql`, `mariadb`); an unknown name is rejected | `postgresql,sqlite,mssql,mysql` |
| `--output`, `-o` | Root output directory | `.protean` |

`--indexes` requires `--domain`: rendering partial-index predicates needs the
live `Index` declarations (the `Q` objects), which an IR file does not carry.

`--dialects` accepts only the dialects the framework renders DDL for:
`mariadb`, `mssql`, `mysql`, `postgresql`, and `sqlite`. A name outside that set
(`oracle`, or a typo like `postgres`) exits with an error naming the accepted
set. Protean has no compiler for such a dialect. Accepting the name would
produce a file named for a dialect that Protean never rendered.

MariaDB is not in the default set. It is accepted when you ask for it, and its
`CREATE INDEX` output matches MySQL's for the index forms Protean emits.

**Output structure**

One `.sql` file per schema name per dialect is written under
`<output>/schemas/<cluster>/`. Elements that share a schema name get one file,
and a dialect that renders no index statement gets none:

```
.protean/
└── schemas/
    └── Order/
        ├── order.indexes.postgresql.sql
        └── order.indexes.sqlite.sql
```

Each file is headed with the element FQN and dialect, followed by the
`CREATE INDEX` statements. Dialects that do not support a partial `where=` or
covering `include=` emit a full index instead. See
[Indexes](../domain-elements/indexes.md) for the declaration syntax and dialect
support matrix.

---

## Schema format

Generated schemas follow JSON Schema Draft 2020-12 with `x-protean-*`
extension fields for domain metadata. See the
[Schema Generation guide](../../guides/compose-a-domain/schema-generation.md)
for the full schema structure reference, including extension fields, nested
`$defs`/`$ref` resolution, and optional field handling.

---

## Error handling

| Condition | Behavior |
|-----------|----------|
| Neither `--domain` nor `--ir` provided | Aborts with error message |
| Both `--domain` and `--ir` provided | Aborts with "mutually exclusive" error |
| Invalid domain path | Aborts with "Error loading Protean domain" |
| IR file not found or invalid JSON | Aborts with descriptive error |
| Element not found (for `show`) | Lists all available elements and aborts |

---

## Domain discovery

The `--domain` option uses the same domain discovery mechanism as other
Protean commands. See [Domain Discovery](project/discovery.md) for the full
resolution logic.
