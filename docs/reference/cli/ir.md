# `protean ir`

The `protean ir` command group inspects a domain's Intermediate
Representation (IR) -- the machine-readable JSON document that captures
domain topology after initialization.

All commands accept a `--domain` option to specify the domain module path.

## Commands

| Command | Description |
|---------|-------------|
| `protean ir show` | Generate and display the domain's IR |
| `protean ir diff` | Compare two IR snapshots and classify breaking changes |
| `protean ir check` | Check whether the materialized IR is fresh or stale |

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

## `protean ir diff`

Compare two IR snapshots and classify changes as breaking or safe.

```bash
# Auto-baseline: compare live domain against .protean/ir.json
protean ir diff --domain my_app.domain

# Compare against a git commit
protean ir diff --domain my_app.domain --base HEAD

# Compare two explicit files
protean ir diff --left baseline.json --right current.json
```

**Options**

| Option | Description | Default |
|--------|-------------|---------|
| `--domain`, `-d` | Domain module path | |
| `--left`, `-l` | Path to baseline IR JSON file | |
| `--right`, `-r` | Path to current IR JSON file | |
| `--base`, `-b` | Git commit/branch/tag for baseline | |
| `--dir` | Path to `.protean/` directory | `.protean` |
| `--format`, `-f` | Output format: `text` or `json` | `text` |

**Exit codes (CI-friendly)**

| Code | Meaning |
|------|---------|
| 0 | No changes detected |
| 1 | Breaking changes found |
| 2 | Non-breaking changes only |

Respects `.protean/config.toml` settings. See
[Compatibility Checking](../../guides/compatibility-checking.md) for
configuration details.

## `protean ir check`

Check whether the materialized IR matches the live domain.

```bash
protean ir check --domain my_app.domain
protean ir check --domain my_app.domain --format json
```

**Options**

| Option | Description | Default |
|--------|-------------|---------|
| `--domain`, `-d` | Path to the domain module | Required |
| `--dir` | Path to `.protean/` directory | `.protean` |
| `--format`, `-f` | Output format: `text` or `json` | `text` |

**Exit codes**

| Code | Meaning |
|------|---------|
| 0 | IR is fresh (matches live domain) |
| 1 | IR is stale (domain has changed) |
| 2 | No materialized IR found |

## Programmatic access

In Python code, call `domain.to_ir()` directly:

```python
domain.init()
ir = domain.to_ir()
```

The returned dict is identical to the JSON output. See
[Inspecting the IR](../../guides/compose-a-domain/inspecting-the-ir.md) for
usage examples.
