# `protean verify`

Run a project's three health checks in order and return one verdict. `verify`
composes the steps you would otherwise run by hand:

1. **Init**: Discover the domain and initialize it (`Domain.init`).
2. **Check**: Run the domain health validation (`Domain.check`), the same
   engine behind [`protean check`](check.md).
3. **Tests**: Run the project's own `pytest` suite in the project directory.

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

`verify` follows the [CLI-wide exit-code convention](conventions.md), with its
stage classes pinned above the shared `0`/`2`. The code is a stable contract,
ordered by precedence (init before check before tests):

| Exit code | Meaning |
|-----------|---------|
| `0` | All green: init, check, and tests all pass. |
| `2` | Usage error: the domain was not found, or `--path` is not a directory. |
| `3` | The domain was found but failed to initialize. |
| `4` | Check failed: a malformed `[lint]` config, or findings at or above the `[lint].level` floor. |
| `5` | Tests failed. |

A malformed command line (an unknown flag, a missing option value) is rejected
by the argument parser **before** `verify` runs and also exits `2`. That is
Click's convention, which the usage class here matches. The table above applies
once `verify` itself starts running.

(These codes shifted up by one from an earlier unreleased set so that `2` is
reserved for usage; see the [v0.18 migration note](../migration/v0-18.md#check-and-verify-machine-output-changed-shape-and-exit-codes).)

The check stage honours `[lint].level` (default `"warn"`), the **same** severity
floor [`protean check`](check.md) uses: `"error"` gates on errors only, `"warn"`
also gates on warnings, `"info"` gates on any finding. A malformed `[lint]` block
(a bad `suppressions` count, a non-table `[lint]`, an invalid `level`) gates as a
check failure too, `verify` validates it the way `check` does. Check and tests both run
even when check fails (so the `--json` envelope carries every stage's result); the
exit code follows the precedence above.

An empty test directory (`pytest` collects nothing and returns `5`) is treated
as a **pass** for the tests stage. The returncode is preserved in the envelope
so "no tests" is distinguishable from "tests passed".

## JSON envelope

`--json` prints a single [result envelope](conventions.md#the-result-envelope)
on stdout: a coarse `status`, the verdict and stage tree under `data`, and the
check-stage diagnostics at the top level.

```json
{
  "version": "0.1.0",
  "status": "pass",
  "data": {
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
  },
  "diagnostics": []
}
```

| Field | Description |
|-------|-------------|
| `status` | Coarse verdict: `pass` (exit 0), `fail` (a failed stage), or `error` (a usage error, exit 2). |
| `data.verdict` | `pass` only when every stage passes; otherwise `fail`. |
| `data.stages.init.status` | `pass` or `fail` once init runs; `skipped` (with no other sub-keys) if `verify` aborts before init, for example when `--path` is not a directory. |
| `data.stages.check` | The `status` plus the `counts`, `errors`, and `diagnostics` from `Domain.check()` (see the [check envelope](check.md#result-envelope)). A malformed `[lint]` config is reported here as a single synthetic error. |
| `data.stages.tests` | The `status`, the pytest `returncode`, and best-effort `passed`/`failed` counts parsed from pytest's summary line. The returncode, not the parsed counts, decides pass/fail. |
| `data.error` | Present only for a usage error caught before any stage ran, for example when `--path` is not a directory. It carries the same human-facing message that goes to stderr in the non-`--json` case. |
| `diagnostics` | The check-stage diagnostics, surfaced at the top level (empty when check never ran). |

When `verify` aborts early (the domain is not found, exit 2; `--path` is not a
directory, exit 2; or init fails, exit 3), the stages that never ran are
reported as a bare `{ "status": "skipped" }` **without** their other sub-keys. A
consumer that reads, say, `data.stages.check.counts` must guard for the skipped
shape (or check the top-level `status`/`data.verdict` first). The domain-not-found
and init-failure cases carry their message under `data.stages.init.error`
instead of `data.error`, since those are tied to the init stage.

## Related

- [`protean check`](check.md): The domain validation step, run on its own.
- [`protean new`](project/new.md): Scaffold a project, then `protean verify` it.
