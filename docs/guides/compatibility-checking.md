# Compatibility checking

Protean's IR (Intermediate Representation) tooling helps you detect breaking
changes to your domain model before they reach production. This guide walks
you through setting up the `.protean/` directory, configuring pre-commit
hooks, and adding compatibility checks to CI.

For the classification rules that determine what counts as a breaking change,
see the [Compatibility Reference](../reference/compatibility/index.md).

---

## Step 1: Materialize the IR baseline

The `.protean/` directory holds your materialized IR snapshot -- the
baseline that changes are compared against. The easiest way to create it
is with the pre-commit hook's `--fix` flag (see [Step 3](#step-3-add-pre-commit-hooks)),
which auto-creates the directory and generates the IR on every commit.

To generate the baseline manually:

```bash
protean ir show --domain myapp.domain > .protean/ir.json
```

Commit `.protean/ir.json` to version control. It serves as the baseline for
detecting changes between releases.

### Multi-domain projects

Projects with multiple bounded contexts use a subdirectory per domain:

```
.protean/
├── config.toml             # Shared configuration (includes [domains] table)
├── identity/
│   └── ir.json
├── catalogue/
│   └── ir.json
└── ordering/
    └── ir.json
```

Configure the `[domains]` table in `.protean/config.toml`:

```toml
[domains]
identity = "identity.domain"
catalogue = "catalogue.domain"
ordering = "ordering.domain"
```

---

## Step 2: Configure strictness

Create `.protean/config.toml` to customize behavior. All settings are
optional -- sensible defaults apply when the file is absent:

```toml
[compatibility]
strictness = "strict"  # "strict" | "warn" | "off"
exclude = ["myapp.internal.LegacyEvent"]

[compatibility.deprecation]
min_versions_before_removal = 3

[staleness]
enabled = true
```

For the full list of configuration keys, see the
[config reference](../reference/compatibility/index.md#proteanconfigtoml-reference).

---

## Step 3: Add pre-commit hooks

Protean ships two [pre-commit](https://pre-commit.com/) hooks. Add them to
your project's `.pre-commit-config.yaml`:

```yaml
repos:
  - repo: local
    hooks:
      - id: protean-check-staleness
        name: Check IR staleness
        entry: uv run protean-check-staleness --domain=myapp.domain
        language: system
        pass_filenames: false
        always_run: true
      - id: protean-check-compat
        name: Check IR compatibility
        entry: uv run protean-check-compat --domain=myapp.domain
        language: system
        pass_filenames: false
        always_run: true
```

!!! note "Why `repo: local`?"
    Protean hooks call `derive_domain()` which imports your application's
    domain modules. A remote `repo:` installs hooks in an isolated virtualenv
    that does not have access to your source code, so the import will fail.
    Using `repo: local` with `language: system` runs the hook in the caller's
    environment. Prefix the `entry` with `uv run` (or activate your virtualenv)
    to ensure the hook executes inside your project's environment where your
    code is importable.

### `protean-check-staleness`

Blocks the commit if `.protean/ir.json` is out of date.

Without `--fix`, a stale check prints the mismatch and suggests a manual
regeneration command. With `--fix`, the hook regenerates the IR, stages the
file with `git add`, and exits 0 -- allowing the commit to proceed.

```yaml
# Auto-fix mode -- never blocks on stale IR
repos:
  - repo: local
    hooks:
      - id: protean-check-staleness
        name: Check IR staleness
        entry: uv run protean-check-staleness --domain=myapp.domain --fix
        language: system
        pass_filenames: false
        always_run: true
```

### `protean-check-compat`

Blocks the commit if breaking IR changes are detected against the baseline
in `HEAD`.

### Multi-domain support

When your `config.toml` has a `[domains]` table, omit the `--domain`
argument. Both hooks iterate over all configured domains automatically:

```yaml
# No --domain needed -- reads [domains] from .protean/config.toml
repos:
  - repo: local
    hooks:
      - id: protean-check-staleness
        name: Check IR staleness
        entry: uv run protean-check-staleness --fix
        language: system
        pass_filenames: false
        always_run: true
      - id: protean-check-compat
        name: Check IR compatibility
        entry: uv run protean-check-compat
        language: system
        pass_filenames: false
        always_run: true
```

Each domain's IR is checked against its own subdirectory
(`.protean/<name>/ir.json`). The hooks exit non-zero if *any* domain fails
its check.

---

## Step 4: Add CI checks

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

## Using the CLI

### `protean ir check`

Compare the live domain against the materialized IR:

```bash
protean ir check --domain myapp.domain
```

Exit codes: 0 (fresh), 1 (stale), 2 (no IR found).

### `protean ir diff`

Compare two IR snapshots with full breaking-change classification:

```bash
# Auto-baseline: compare live domain against .protean/ir.json
protean ir diff --domain myapp.domain

# Compare against a specific git commit
protean ir diff --domain myapp.domain --base HEAD

# Compare two explicit files
protean ir diff --left baseline.json --right current.json
```

Exit codes: 0 (no changes), 1 (breaking changes), 2 (non-breaking only).

When `strictness = "warn"`, breaking changes are reported but the exit code
is 0. When `strictness = "off"`, the command exits 0 immediately.

For the full CLI reference, see [`protean ir`](../reference/cli/ir.md).

---

!!! tip "See also"
    - [Compatibility Reference](../reference/compatibility/index.md)
      -- Breaking change rules, three-tier taxonomy, deprecation lifecycle,
      and config key reference.
    - [`protean ir` CLI Reference](../reference/cli/ir.md)
      -- Full CLI command documentation.
    - [ADR-0004](../adr/0004-release-workflow-and-breaking-change-policy.md)
      -- Release workflow and breaking change policy.
