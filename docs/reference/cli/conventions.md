# CLI conventions: the result envelope and exit codes

Protean is standardizing two contracts so that a script or an agent can consume a
command's output uniformly: one **result envelope** for machine-readable output,
and one **exit-code convention**. This page is the durable reference for both, and
the shape a new command that emits `--json` output should follow.

`check` and `verify` follow these contracts today. The other commands that print
JSON (`upgrade-check`, `ir diff`, `ir check`) predate them and are **not yet
converged**: their exit codes and output shapes still differ. Converging them is
a separate follow-on; until then, only `check` and `verify` are guaranteed to
match what this page describes.

## The result envelope

Every command that emits machine-readable output (under `--json`, or
`--format json` for `check`) wraps its result in one stable JSON object:

```json
{
  "version": "0.1.0",
  "status": "pass",
  "data": { "...": "command-specific detail" },
  "diagnostics": [ "...typed Diagnostic records..." ]
}
```

| Field | Type | Description |
|-------|------|-------------|
| `version` | str | Semantic version of the envelope format. |
| `status` | str | Coarse verdict: `pass`, `fail`, or `error` (see below). |
| `data` | object | The command's own detail: check's report, verify's stage tree, and so on. |
| `diagnostics` | array | The typed [`Diagnostic`](../fitness-functions.md) records (may be empty). |

`status` is the coarse verdict that maps to the exit-code class:

- `pass`: Success (exit `0`).
- `fail`: The command ran and found a failure it is designed to detect (a
  gating diagnostic, a failed stage). The fine-grained severity is in `data` and
  `diagnostics`, not the status.
- `error`: A usage or environment error it could not run past (a bad option, no
  or unloadable domain, malformed config, IO). Maps to the usage class (exit `2`).

The envelope ships a pinned, versioned JSON Schema at
`src/protean/cli/schema/v0.1.0/envelope.schema.json` (mirroring the IR schema
precedent). A conformance test validates the `check` and `verify` `--json` output
against it, so the shape is enforced, not just documented.

`data` and `diagnostics` split the payload deliberately, so a consumer should
read **both**: `diagnostics` carries the lint findings (the recoverable,
per-element diagnostics), while `data` carries the command's own detail and its
*fatal* errors: a domain that would not load, a malformed `[lint]` config, a
failed init stage. Those fatal errors live under `data` (e.g. `data.error`, or
`data.stages.init.error` for `verify`), not in `diagnostics`. A diagnostics-only
consumer will miss them.

SARIF and GitHub-annotations output (`check --format sarif` /
`--format github-annotations`) are **not** wrapped: they are external standard
schemas consumed by other tools, and stay as-is.

## The exit-code convention

| Exit code | Meaning |
|-----------|---------|
| `0` | Success. |
| `1` | The command ran and reports a failure it is designed to detect. The severity/stage detail is in the envelope, not the code. |
| `2` | A usage or environment error it could not run past: a bad option or argument (Click's own default), no or unloadable domain, malformed config, IO. |
| `>=3` | Command-specific failure classes, documented per command. |

Because `2 = usage` is Click's own default for a malformed command line, a
command that sets no explicit exit code already conforms.

### Per-command codes

**`protean check`**

| Exit code | Meaning |
|-----------|---------|
| `0` | Nothing at or above the configured `[lint].level` floor. |
| `1` | A findings failure: validator errors, or a warning/info at or above the floor. |
| `2` | Usage/environment: a bad `--domain`, `--level`, or `--format`; a domain that will not load; a malformed `[lint]` config. |

**`protean verify`** (the stage classes are pinned above the shared `0`/`2`):

| Exit code | Meaning |
|-----------|---------|
| `0` | All green: init, check, and tests pass. |
| `2` | Usage: the domain was not found, or `--path` is not a directory. |
| `3` | Init failed: the domain was found but did not initialize. |
| `4` | Check failed: a malformed `[lint]` config, or findings at or above the floor. |
| `5` | Tests failed. |

## Clean stdout

Under machine-readable output, stdout carries **only** the envelope: exactly
one JSON object and nothing else. Every log line, warning, and human error
message goes to stderr, so `protean check --format json | jq` (or
`protean verify --json | jq`) stays parseable.

## Related

- [`protean check`](check.md): The exemplar command.
- [`protean verify`](verify.md): Init, check, and tests in one verdict.
- [Migrating to 0.18](../migration/v0-18.md): The shape and exit-code changes.
