# `protean dx`

The `protean dx` command group writes and maintains the agent-facing files that
make a coding agent correct with the installed framework version. The files are
composed from data that ships inside the `protean` package, so an agent reads
guidance that matches the installed code.

This cut writes two files into a target project:

- `AGENTS.md`: the canonical, cross-agent instruction file. Its body has two
  layers. The first is the positive guidance from the packaged AGENTS.md source.
  The second is the negative hard-rules section, one rule for every error-level
  diagnostic code Protean can raise, built from the same diagnostics registry as
  [`protean docs generate --type=agents`](./docs.md). Both layers are stamped
  with the installed version.
- `CLAUDE.md`: a one-line bridge, `@AGENTS.md`, that points Claude Code at the
  canonical file.

The per-editor rule files (Cursor, Copilot, opencode) and the `.mcp.json`
registration are separate commands that land later on the same epic.

## Managed blocks

Each file is co-owned. The framework writes a block framed by two HTML comment
markers, `<!-- PROTEAN:BEGIN protean -->` and `<!-- PROTEAN:END protean -->`, and
you own every line around it. Re-running `install` or `refresh` rewrites the
block and preserves your own edits outside it.

A state file at `.protean/dx-state.json` records what the writer last wrote per
target. It tells a version change (a safe rewrite) apart from an edit you made
inside the block (a conflict the writer refuses to overwrite). Commit the state
file so the conflict check works across machines. The design is recorded in
[ADR-0037](../../../adr/0037-idempotent-file-projection.md).

## Verbs

```shell
protean dx install     # write AGENTS.md and the CLAUDE.md bridge
protean dx refresh     # re-render the blocks to the installed version
protean dx diff        # preview what install would change; write nothing
protean dx check       # exit non-zero when a target has drifted; write nothing
```

`install` creates a missing file and refreshes a stale block. `refresh` is the
same idempotent apply, run after upgrading Protean. `diff` and `check` write
nothing: `diff` is the preview and `check` is the CI gate.

A target has drifted when it is missing, its block is stale against the installed
version, or you edited inside the block. `check` reports each target and exits
non-zero when any has drifted.

### Options

- `--path`, `-p`: The project directory to write into or check. Defaults to the
  current directory.

### Exit codes

- `0`: the command succeeded. For `check`, every target is up to date.
- `1`: for `check`, a target has drifted. For `install` and `refresh`, a block
  conflicts with a hand edit and was left untouched.
- `2`: a filesystem error, such as an unreadable or malformed target.

A conflict on one file does not stop the others. `install` applies every file it
safely can, reports the conflict, and then exits non-zero.

## In CI

Wire `check` into a pipeline so a project's agent files stay in step with the
framework. It writes nothing and fails the job on drift.

```shell
protean dx check
```
