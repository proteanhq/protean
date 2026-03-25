# Compatibility checking

Protean's IR (Intermediate Representation) tooling helps you detect breaking
changes to your domain model before they reach production. This guide covers
the `.protean/` directory, configuration, pre-commit hooks, and CI
integration.

---

## The `.protean/` directory

The `.protean/` directory is your project's materialized IR workspace. It
contains:

```
.protean/
├── ir.json        # Materialized IR snapshot of your domain
└── config.toml    # Optional configuration for compatibility checks
```

Generate the IR snapshot with:

```bash
protean ir show --domain my_app.domain > .protean/ir.json
```

Commit `.protean/ir.json` to version control. It serves as the baseline for
detecting changes between releases.

### Multi-domain projects

Projects with multiple bounded contexts use a subdirectory per domain:

```
.protean/
├── config.toml             # Shared configuration (includes [domains] table)
├── identity/
│   └── ir.json             # IR for the identity bounded context
├── catalogue/
│   └── ir.json             # IR for the catalogue bounded context
└── ordering/
    └── ir.json             # IR for the ordering bounded context
```

See the [`[domains]` configuration](#domains) and
[multi-domain hooks](#multi-domain-support) sections below.

---

## Configuration

Create `.protean/config.toml` to customize compatibility checking behavior.
All settings are optional --- sensible defaults apply when the file is absent.

```toml
[compatibility]
strictness = "strict"  # "strict" | "warn" | "off"
exclude = ["myapp.internal.LegacyEvent"]

[compatibility.deprecation]
min_versions_before_removal = 3

[staleness]
enabled = true

[domains]
identity = "identity.domain"
catalogue = "catalogue.domain"
ordering = "ordering.domain"
```

### `[compatibility]`

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `strictness` | string | `"strict"` | `"strict"` exits non-zero on breaking changes. `"warn"` reports but allows. `"off"` skips checking entirely. |
| `exclude` | list of strings | `[]` | Fully-qualified names of elements to exclude from compatibility checks. |

### `[compatibility.deprecation]`

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `min_versions_before_removal` | integer | `3` | Minimum minor versions a deprecated element must survive before removal. |

### `[staleness]`

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `enabled` | boolean | `true` | Whether the staleness check (`protean ir check`) is active. Set to `false` to skip. |

### `[domains]`

Maps logical domain names to their module paths. When present, pre-commit
hooks iterate over all configured domains automatically --- no `--domain`
argument needed. Each domain's IR is stored under `.protean/<name>/ir.json`.

```toml
[domains]
identity = "identity.domain"
catalogue = "catalogue.domain"
ordering = "ordering.domain"
```

| Key | Type | Description |
|-----|------|-------------|
| `<name>` | string | Dotted module path to the domain (e.g. `"identity.domain"`). The key is the logical name used as the subdirectory. |

---

## Breaking change rules

Protean classifies changes to persisted domain elements using these rules:

| Change | Classification |
|--------|---------------|
| Add optional field (or with default) | Safe |
| Add required field without default | **Breaking** |
| Remove field from any persisted element | **Breaking** |
| Change field type | **Breaking** |
| Remove an element | **Breaking** |
| Add a new element | Safe |
| Visibility public to internal | **Breaking** |
| Visibility internal to public | Safe |
| Change `__type__` string | **Breaking** |

These rules apply to all persisted elements: aggregates, entities, value
objects, commands, events, database models, and projections.

### Three-tier breaking change taxonomy

Protean follows a tiered approach to breaking changes (see
[ADR-0004](../adr/0004-release-workflow-and-breaking-change-policy.md)):

- **Tier 1 (Surface):** Renamed classes, moved imports, changed signatures.
  Mitigated with `DeprecationWarning` surviving 2+ minor versions.
- **Tier 2 (Behavioral):** Same signature, different behavior. Mitigated
  with opt-in flags over 3 minor versions.
- **Tier 3 (Structural):** Persistence format, event schema, serialization
  changes. Mitigated with versioned schemas and migration documentation.

The IR compatibility checker focuses on **Tier 3** structural changes.

---

## CLI commands

### `protean ir check`

Compare the live domain against the materialized IR:

```bash
protean ir check --domain my_app.domain
```

Exit codes: 0 (fresh), 1 (stale), 2 (no IR found).

### `protean ir diff`

Compare two IR snapshots with full breaking-change classification:

```bash
# Auto-baseline: compare live domain against .protean/ir.json
protean ir diff --domain my_app.domain

# Compare against a specific git commit
protean ir diff --domain my_app.domain --base HEAD

# Compare two explicit files
protean ir diff --left baseline.json --right current.json
```

Exit codes: 0 (no changes), 1 (breaking changes), 2 (non-breaking only).

When `strictness = "warn"`, breaking changes are reported but the exit code
is 0. When `strictness = "off"`, the command exits 0 immediately.

---

## Pre-commit hooks

Protean ships two [pre-commit](https://pre-commit.com/) hooks. Add them to
your project's `.pre-commit-config.yaml`:

```yaml
- repo: https://github.com/proteanhq/protean
  rev: v0.15.0  # use the version you depend on
  hooks:
    - id: protean-check-staleness
      args: [--domain=myapp.domain]
    - id: protean-check-compat
      args: [--domain=myapp.domain]
```

### `protean-check-staleness`

Blocks the commit if `.protean/ir.json` is out of date.

| Flag | Description |
|------|-------------|
| `--domain`, `-d` | Domain module path (optional when `[domains]` is configured). |
| `--dir` | Path to the `.protean/` directory (default: `.protean`). |
| `--fix`, `-f` | Auto-regenerate stale IR and stage the updated file. |

Without `--fix`, a stale check prints the mismatch and suggests a manual
regeneration command. With `--fix`, the hook regenerates the IR, writes it
to `ir.json`, stages the file with `git add`, and exits 0 --- allowing the
commit to proceed.

```yaml
# Auto-fix mode --- never blocks on stale IR
- id: protean-check-staleness
  args: [--domain=myapp.domain, --fix]
```

Respects `staleness.enabled` in `config.toml`.

### `protean-check-compat`

Blocks the commit if breaking IR changes are detected against the baseline
in `HEAD`.

| Flag | Description |
|------|-------------|
| `--domain`, `-d` | Domain module path (optional when `[domains]` is configured). |
| `--base`, `-b` | Git ref for baseline IR (default: `HEAD`). |
| `--dir` | Path to the `.protean/` directory (default: `.protean`). |

Respects `compatibility.strictness` and `compatibility.exclude`
in `config.toml`.

### Multi-domain support

When your project has multiple bounded contexts, configure the `[domains]`
table in `.protean/config.toml` (see [Configuration](#domains) above) and
omit the `--domain` argument. Both hooks will iterate over all configured
domains automatically:

```yaml
# No --domain needed --- reads [domains] from .protean/config.toml
- repo: https://github.com/proteanhq/protean
  rev: v0.15.0
  hooks:
    - id: protean-check-staleness
      args: [--fix]
    - id: protean-check-compat
```

Each domain's IR is checked against its own subdirectory
(`.protean/<name>/ir.json`). The hooks exit non-zero if *any* domain fails
its check.

---

## CI integration

### GitHub Actions

Add a compatibility check step to your CI workflow:

```yaml
- name: Check IR compatibility
  run: |
    protean ir diff --domain myapp.domain --base origin/main
```

The command exits with code 1 on breaking changes, which fails the CI step.

### pytest warning filters

Turn Protean deprecation warnings into test failures:

```toml
# pyproject.toml
[tool.pytest.ini_options]
filterwarnings = [
    "error::DeprecationWarning:protean.*",
]
```

This catches deprecated API usage during development rather than after a
breaking release.

---

## Deprecation lifecycle

When deprecating a domain element or field:

1. **Mark as deprecated** with a `DeprecationWarning` that includes the
   removal version (see
   [ADR-0004](../adr/0004-release-workflow-and-breaking-change-policy.md)
   for the deprecation pattern).
2. **Keep the deprecated API** for at least `min_versions_before_removal`
   minor versions (default: 3).
3. **Add to `exclude`** in `config.toml` if the element should not trigger
   breaking change alerts during its deprecation period.
4. **Remove** in a cleanup release after the survival window.

The `protean ir diff` command distinguishes expected removals (deprecated
elements past their removal version) from unexpected removals.
