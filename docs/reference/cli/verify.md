# `protean verify`

Run a project's three health checks in order and return one verdict. `verify`
composes the steps you would otherwise run by hand:

1. **Init** — discover the domain and initialize it (`Domain.init`).
2. **Check** — run the domain health validation (`Domain.check`), the same
   engine behind [`protean check`](check.md).
3. **Tests** — run the project's own `pytest` suite in the project directory.

It is the fastest way to confirm a freshly scaffolded project actually works,
and a single gate to run in CI.

```bash
# Verify the project discovered from the current directory
protean verify

# Explicit domain and project directory
protean verify --domain=my_app.domain --path=.

# Machine-readable envelope (CI-friendly)
protean verify --json
```

## Options

| Option | Short | Default | Description |
|--------|-------|---------|-------------|
| `--domain` | `-d` | `.` | Path to the domain module (e.g. `my_app.domain`). Uses the same [domain discovery](project/discovery.md) as other commands. |
| `--path` | | `.` | Project directory to run the tests in. `pytest` is invoked here, so it is where your project's test discovery is rooted. |
| `--json` | | `false` | Emit a JSON envelope on stdout instead of the human table. |

`verify` runs `pytest` in a child process using the same interpreter that runs
Protean (`sys.executable -m pytest`). If the project directory has a `src/`
folder (the src-layout a scaffolded project uses), that folder is put on the
child's `PYTHONPATH` so the project's own tests can import the package even
before it is installed.

## Exit codes

The exit code is a stable contract, ordered by precedence (init before check
before tests):

| Exit code | Meaning |
|-----------|---------|
| `0` | All green — init, check, and tests all pass. |
| `1` | `verify`'s own error — bad arguments, or the domain was not found. |
| `2` | The domain was found but failed to initialize. |
| `3` | Check failed — the domain has errors or warnings. |
| `4` | Tests failed. |

Check "fails" on **errors or warnings** (`status` `fail`/`warn`), matching
`protean check`'s default `[lint].level="warn"` floor. An info-only domain still
passes. Check and tests both run even when check fails (so the `--json` envelope
carries every stage's result); the exit code follows the precedence above.

An empty test directory — `pytest` collects nothing and returns `5` — is treated
as a **pass** for the tests stage. The returncode is preserved in the envelope so
"no tests" is distinguishable from "tests passed".

## JSON envelope

`--json` prints a single JSON document on stdout:

```json
{
  "verdict": "pass",
  "stages": {
    "init": { "status": "pass", "error": null },
    "check": {
      "status": "pass",
      "counts": { "errors": 0, "warnings": 0, "infos": 0 },
      "errors": [],
      "diagnostics": []
    },
    "tests": { "status": "pass", "returncode": 0, "passed": 12, "failed": 0 }
  }
}
```

| Field | Description |
|-------|-------------|
| `verdict` | `pass` only when every stage passes; otherwise `fail`. |
| `stages.init.status` | `pass`, `fail`, or `skipped`. `skipped` when an earlier stage aborted the run. |
| `stages.check` | The `status` plus the `counts`, `errors`, and `diagnostics` from `Domain.check()` (see the [check result schema](check.md#result-schema)). |
| `stages.tests` | The `status`, the pytest `returncode`, and best-effort `passed`/`failed` counts parsed from pytest's summary line. The returncode — not the parsed counts — decides pass/fail. |

When init fails, `check` and `tests` are reported as `skipped` (they never ran).

## Related

- [`protean check`](check.md) — the domain validation step, run on its own.
- [`protean new`](project/new.md) — scaffold a project, then `protean verify` it.
