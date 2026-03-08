# `protean ir`

The `protean ir` command group inspects a domain's Intermediate
Representation (IR) -- the machine-readable JSON document that captures
domain topology after initialization.

All commands accept a `--domain` option to specify the domain module path.

## Commands

| Command | Description |
|---------|-------------|
| `protean ir show` | Generate and display the domain's IR |

## `protean ir show`

Loads the domain, calls `domain.init()`, and outputs the IR as JSON or a
human-readable summary.

```bash
# Full JSON output (pipe to jq, save to file, etc.)
protean ir show --domain=my_app.domain

# Human-readable summary with element counts and cluster details
protean ir show --domain=my_app.domain --format=summary

# Save to a file for version control
protean ir show --domain=my_app.domain > domain-ir.json
```

**Options**

| Option | Description | Default |
|--------|-------------|---------|
| `--domain`, `-d` | Path to the domain module (e.g. `my_app.domain`) | Required |
| `--format`, `-f` | Output format: `json` or `summary` | `json` |

**JSON output**

The full IR document, pretty-printed with 2-space indentation. Contains all
sections: `domain`, `clusters`, `projections`, `flows`, `elements`, and
`diagnostics`. See the [IR specification](../../concepts/internals/ir-specification.md)
for the complete structure reference.

**Summary output**

A compact overview showing:

- Domain name, IR version, and checksum
- Element counts by type (table)
- Cluster breakdown (entities, value objects, commands, events per aggregate)
- Diagnostic warnings, if any

```
Domain: Ordering
IR Version: 0.1.0
Checksum: sha256:a1b2c3d4...

     Element Counts
┏━━━━━━━━━━━━━━━━━━┳━━━━━━━┓
┃ Element Type      ┃ Count ┃
┡━━━━━━━━━━━━━━━━━━╇━━━━━━━┩
│ AGGREGATE         │     2 │
│ COMMAND           │     3 │
│ COMMAND_HANDLER   │     2 │
│ EVENT             │     4 │
│ EVENT_HANDLER     │     1 │
│ ENTITY            │     1 │
│ VALUE_OBJECT      │     1 │
└───────────────────┴───────┘

Clusters: 2
  Order: 1 entities, 1 VOs, 2 commands, 3 events
  Payment: 0 entities, 0 VOs, 1 commands, 1 events
```

## Programmatic access

In Python code, call `domain.to_ir()` directly:

```python
domain.init()
ir = domain.to_ir()
```

The returned dict is identical to the JSON output. See
[Inspecting the IR](../../guides/compose-a-domain/inspecting-the-ir.md) for
usage examples.
