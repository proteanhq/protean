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

Either `--domain` or `--ir` is required; they are mutually exclusive.

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
