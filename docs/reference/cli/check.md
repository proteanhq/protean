# `protean check`

Validate a Protean domain and report errors, warnings, and diagnostics. Unlike
`protean server` or `protean shell`, `check` does **not** initialize adapters.
It resolves references, wires handlers, runs every validation check, and builds
the IR to collect [architecture fitness function](../fitness-functions.md)
diagnostics. It is designed to run in CI and pre-commit hooks.

```bash
# Check the domain discovered from the current directory
protean check

# Check an explicit domain module
protean check --domain=my_app.domain

# Emit machine-readable output
protean check --format=json
protean check --format=sarif > protean.sarif
```

## Options

| Option | Short | Default | Description |
|--------|-------|---------|-------------|
| `--domain` | `-d` | `.` | Path to the domain module (e.g. `my_app.domain`). Uses the same [domain discovery](project/discovery.md) as other commands. |
| `--format` | `-f` | `rich` | Output format: `rich`, `json`, `sarif`, or `github-annotations`. |
| `--level` | `-l` | `info` | Minimum severity to **display**: `error`, `warning`, or `info`. Filters the `rich`/`--quiet` human output only. It never changes the exit code, and it never filters the machine formats (`json`, `sarif`, `github-annotations`). |
| `--quiet` | `-q` | `false` | Show only a one-line count summary and set the exit code. |

## Output formats

| Format | Description |
|--------|-------------|
| `rich` | Human-readable table (default). |
| `json` | The shared CLI [result envelope](#result-envelope), `indent=2`, keys sorted. |
| `sarif` | [SARIF 2.1.0](https://sarifweb.azurewebsites.net/) for GitHub Code Scanning. |
| `github-annotations` | GitHub Actions `::error`/`::warning`/`::notice` workflow commands. |

The `json`, `sarif`, and `github-annotations` formats always emit the
**unfiltered** set of findings regardless of `--level`, because they feed
machines (an agent consuming the envelope, a Code Scanning upload, CI
annotations) where a display filter must not silently drop findings. So a
`json` envelope with `status="fail"` always carries the diagnostics and counts
that caused it. Filter with `jq` if you want a subset.

## Exit codes

`check` follows the [CLI-wide exit-code convention](conventions.md). The code is
driven by the **unfiltered** counts and gated by the `[lint].level` config key
(the severity *floor*), not by the `--level` display flag:

| Exit code | Meaning |
|-----------|---------|
| `0` | Nothing at or above the configured floor. |
| `1` | A findings failure: validator errors, or a warning/info at or above the floor. The severity detail is in the envelope, not the code. |
| `2` | A usage or environment error: a bad `--domain`, `--level`, or `--format`; a domain that will not load; or a malformed `[lint]` config. |

The single findings-failure code (`1`) replaced an earlier split (errors `1`,
warnings `2`); the severity now lives in the envelope. Load and config errors,
previously `1`, are usage errors (`2`).

`[lint].level` maps as follows (default `warn`):

| `[lint].level` | Gates on |
|----------------|----------|
| `error` | Errors only (warnings and infos never gate). |
| `warn` (default) | Errors and warnings. |
| `info` | Errors, warnings, and infos. |

See the [`[lint]` configuration reference](../configuration/index.md#lint) for
the full set of config keys (`level`, `suppressions`, `aggregate_size_limit`,
`handler_breadth_limit`, `check_infra_imports`, `rules`).

## Result envelope

The `--format=json` output is the shared CLI
[result envelope](conventions.md#the-result-envelope): a coarse `status`, the
check report under `data`, and the diagnostics list at the top level.

```json
{
  "version": "0.1.0",
  "status": "fail",
  "data": {
    "domain": "my_app",
    "status": "warn",
    "errors": [],
    "counts": { "errors": 0, "warnings": 1, "infos": 0 }
  },
  "diagnostics": [
    {
      "category": "aggregate_design",
      "code": "CROSS_AGGREGATE_REFERENCE",
      "element": "my_app.ordering.Order",
      "field": "customer",
      "level": "warning",
      "message": "Order.customer references another aggregate root",
      "rule": {
        "rationale": "Aggregates coordinate other aggregates by identity, not by object reference...",
        "fix": "Hold the other aggregate by its identifier instead of a Reference..."
      },
      "suggestion": "Hold the other aggregate by its identifier instead of a Reference..."
    }
  ]
}
```

**Envelope fields**

| Field | Type | Description |
|-------|------|-------------|
| `version` | str | Envelope format version. |
| `status` | str | Coarse verdict: `pass` (exit 0), `fail` (a findings failure, exit 1), or `error` (a usage/environment error, exit 2). |
| `data` | object | The check report (fields below). |
| `diagnostics` | list | Fitness function findings (see below). Carried at the top level, not under `data`. |

**`data` fields**

| Field | Type | Description |
|-------|------|-------------|
| `domain` | str | The domain name. |
| `status` | str | Fine-grained status: `pass`, `info`, `warn`, or `fail`. |
| `errors` | list | Validator errors (malformed domains). Each has `code` and `message` and is always fatal. Present only when the domain fails to build; when non-empty, `diagnostics` is empty. |
| `counts` | object | `{errors, warnings, infos}` tallies. |

On a usage/environment error (`status: "error"`, exit 2) `data` carries a single
`error` message instead of the report, and `diagnostics` is empty.

**Diagnostic fields**

| Field | Type | Description |
|-------|------|-------------|
| `category` | str | Rule category, one of `aggregate_design`, `bounded_context`, `handler_completeness`, `naming_conventions`, `persistence`, `versioning`, `deprecation`, or `custom`. |
| `code` | str | The rule code (e.g. `CROSS_AGGREGATE_REFERENCE`). See the [catalog](../fitness-functions.md). |
| `element` | str | Fully-qualified name of the offending element. |
| `field` | str | The offending field, on field-scoped rules only. |
| `level` | str | `warning` or `info`. |
| `message` | str | Human-readable description of this specific finding. |
| `rule` | object | Rule metadata: `rationale` (why the rule exists) and `fix` (suggested remediation). |
| `suggestion` | str | Remediation text. Currently equals `rule.fix`; reserved for AI-populated, context-aware text in a future release. |

## CI integration

Emit a SARIF document for GitHub Code Scanning, or inline annotations without it:

```bash
protean check --domain=my_app.domain --format=sarif > protean.sarif
protean check --domain=my_app.domain --format=github-annotations
```

See the [Architecture Fitness Functions
guide](../../guides/architecture-fitness-functions.md#ci-integration) for the
full CI walkthrough: the GitHub Actions workflow, SARIF upload, and how to
choose the gating floor.

## Related

- [Architecture Fitness Functions guide](../../guides/architecture-fitness-functions.md): Running, suppressing, and extending the checks.
- [Fitness Function Catalog](../fitness-functions.md): Every rule, its rationale, and its fix.
- [`[lint]` configuration](../configuration/index.md#lint), config keys.
- [`protean upgrade-check`](upgrade-check.md): A separate read-only 0.16 upgrade diagnostic.
