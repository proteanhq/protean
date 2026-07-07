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

# Save a canonical baseline for version control (no volatile timestamp)
protean ir show --domain=my_app.domain --canonical > .protean/ir.json
```

**Options**

| Option | Description | Default |
|--------|-------------|---------|
| `--domain`, `-d` | Path to the domain module (e.g. `my_app.domain`) | Required |
| `--format`, `-f` | Output format: `json` or `summary` | `json` |
| `--canonical` | Omit the volatile `generated_at` timestamp (json format only) | `false` |

**Canonical baseline output**

By default the JSON output includes a `generated_at` materialization
timestamp, which changes on every regeneration. When committing
`.protean/ir.json` as a baseline for `protean ir diff`, that timestamp is
pure noise: it produces a one-line diff on every `protean ir show` even when
nothing about the domain changed.

Pass `--canonical` to omit `generated_at`. The `$schema`, `ir_version`,
`checksum`, and `elements` keys are retained (they are content-derived or
version markers, and are ignored by `ir diff`/`ir check` alike). A canonical
baseline therefore changes **only** when the domain contract changes.

`--canonical` has no effect with `--format=summary`, which never prints the
timestamp.

**JSON output**

The full IR document, pretty-printed with 2-space indentation. Contains all
sections: `domain`, `clusters`, `projections`, `flows`, `elements`, and
`diagnostics`. See the [IR specification](../../concepts/internals/ir-specification.md)
for the complete structure reference.

Logs are written to stderr, so the JSON on stdout is safe to pipe (`protean ir
show ... | jq`) or redirect to a file without log lines corrupting it.

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

**Avro compatibility verdict.** Alongside the breaking/safe classification, the
diff reports an Avro-style verdict — `BACKWARD`, `FORWARD`, `FULL`, or `NONE` —
matching the rules a schema registry applies to the Avro that
`protean schema generate --format avro` emits:

| Verdict | Meaning |
|---------|---------|
| `BACKWARD` | A consumer on the new schema can read data written with the old schema |
| `FORWARD` | A consumer on the old schema can read data written with the new schema |
| `FULL` | Both `BACKWARD` and `FORWARD` |
| `NONE` | Neither |

Adding an optional field (or a required field with a static default) is `FULL`;
adding a required field without a default is not `BACKWARD`; removing a required
field is not `FORWARD`; a type change is `NONE`. A declared rename is `BACKWARD`
(the emitted schema carries Avro `aliases`), or `FULL` when the old field was
optional or carried a static default. Visibility flips are payload-neutral for
the verdict (they stay breaking).

One rule is **Protean-specific**: an upcaster that covers the version bump makes
an otherwise-incompatible change `BACKWARD`, because Protean rewrites old
payloads to the new shape at read time. A plain schema registry has no knowledge
of upcasters and would still report the underlying change (e.g. `NONE` for a
type change) — so this clause reflects what *Protean* can decode, not what a
registry alone would conclude.

The top-level verdict is the domain-wide intersection (the conservative worst
case). In `--format json`, the `compatibility` block also carries
`avro_verdicts` (a per-element breakdown, since Avro compatibility is
per-subject) and the full classified report. The verdict covers the classified
schema changes; it is informational — the exit code is still governed by
`[compatibility] strictness` and the breaking-change classification.

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
