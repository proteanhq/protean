# `protean dx`

The `protean dx` command group writes and maintains the agent-facing files that
make a coding agent correct with the installed framework version. The files are
composed from data that ships inside the `protean` package, so an agent reads
guidance that matches the installed code.

It writes two sets of files into a target project. The canonical set:

- `AGENTS.md`: the canonical, cross-agent instruction file. Its body has two
  layers. The first is the positive guidance from the packaged AGENTS.md source.
  The second is the negative hard-rules section, one rule for every error-level
  diagnostic code Protean can raise, built from the same diagnostics registry as
  [`protean docs generate --type=agents`](./docs.md). Both layers are stamped
  with the installed version.
- `CLAUDE.md`: a one-line bridge, `@AGENTS.md`, that points Claude Code at the
  canonical file.
- `.mcp.json`: the registration a client reads to launch Protean's MCP server
  (`protean mcp`). It is a structured JSON merge scoped to the
  `mcpServers.protean` key-path, so an existing `.mcp.json` keeps every other
  server you configured; `install` writes and reconciles only its own entry.

The per-editor set, one file each for Cursor, Copilot, and opencode:

- `.cursor/rules/protean.mdc`: Cursor's rule file. It carries MDC frontmatter
  (with `globs: "**/*.py"`, so the rule applies to Python files) and the same
  composed guidance `AGENTS.md` carries. Cursor reads `AGENTS.md` natively for the
  always-on layer, so this rule is scoped to code. Protean owns the whole file,
  since the MDC frontmatter must start at line 1 and leaves no room for a marker
  above it.
- `.github/copilot-instructions.md`: Copilot's instructions, the composed guidance
  in an HTML-comment managed block, so the file stays co-owned with your own
  Copilot instructions.
- `opencode.json`: opencode's config. It manages one `mcp.protean` entry with
  opencode's launch shape (`type: "local"`, `command: ["protean", "mcp"]`,
  `enabled: true`) and keeps every other key. opencode reads `AGENTS.md` natively,
  so it gets no separate instruction file: this config only supplies the MCP
  registration.

## Managed regions

Each file is co-owned, except the Cursor rule file, which Protean owns whole. For
the Markdown files (`AGENTS.md`, `CLAUDE.md`, `.github/copilot-instructions.md`),
the framework writes a block framed by two HTML comment markers,
`<!-- PROTEAN:BEGIN protean -->` and `<!-- PROTEAN:END protean -->`, and you own
every line around it. For the JSON files (`.mcp.json`, `opencode.json`), the
framework owns only its own key-path (`mcpServers.protean`, `mcp.protean`) and you
own every other key, including your other servers. For the Cursor rule file, the
framework owns the whole file, so any hand edit to it is a conflict. Re-running
`install` or `refresh` rewrites the framework's region and preserves your own
edits around it.

A state file at `.protean/dx-state.json` records what the writer last wrote per
target. It tells a version change (a safe rewrite) apart from an edit you made
inside the framework's region (a conflict the writer refuses to overwrite). The
conflict line names the region it means: the managed block for a Markdown file,
the managed key (`mcpServers.protean`, `mcp.protean`) for a JSON file, the whole
file for the Cursor rule. Commit the state file so the conflict check works across
machines. The design is recorded in
[ADR-0037](../../../adr/0037-idempotent-file-projection.md).

For any managed-block Markdown file (`AGENTS.md`, `CLAUDE.md`, and
`.github/copilot-instructions.md`), `install` refuses a pre-existing file that has
no `PROTEAN` markers and writes nothing to it, so it never overwrites a file you
wrote by hand. This covers a `.github/copilot-instructions.md` you already keep, an
`AGENTS.md` you wrote yourself, and the marker-less `AGENTS.md` a `protean new`
before 0.18 wrote. It reports an error until you remove or rename that file and run
`install`, which then writes the managed version.

A project made with `protean new` from 0.18 on needs none of this. `protean new`
writes the same managed `AGENTS.md` and `CLAUDE.md` bridge that `install` writes, at
the same version, and records them in `.protean/dx-state.json`. So a fresh project is
already dx-managed: `install`, `refresh`, and `check` all work on it with no manual
step. `protean new` writes only this baseline; `.mcp.json` and the per-editor files
stay `install` choices, since you pick your own editors. `refresh` keeps it that way:
it re-renders what the project already has and never adds an optional file, so
upgrading a scaffolded project leaves it baseline-only until you run `install`.

## Verbs

```shell
protean dx install       # write the canonical and per-editor files
protean dx refresh       # re-render what is installed, to the installed version
protean dx diff          # preview what install would change (unified diff); write nothing
protean dx check         # exit non-zero when a target has drifted; write nothing
protean dx build-plugin  # render the packaged skills into the Claude Code plugin tree
```

`install` creates a missing file and refreshes a stale managed region, across every
target. It is the verb that opts a project into `.mcp.json` and the per-editor
files. `refresh` is the same idempotent apply, run after upgrading Protean, scoped
to what the project already has: the required baseline plus every optional target
already installed. So `refresh` updates a project without adding a file you did not
choose. `diff` and `check` write nothing: `diff` is the preview, printing a unified
diff of each pending change, and `check` is the CI gate. `build-plugin` is described
in [Building the Claude Code plugin](#building-the-claude-code-plugin) below; unlike
the other verbs, it renders Protean's own committed plugin tree rather than files
in your project.

A target has drifted when it is missing, its managed region is stale against the
installed version, or you edited inside that region. `check` reports each verified
target, naming the region it means, and exits non-zero when any has drifted.

`check` verifies a required baseline plus whatever else is installed, the same
scope `refresh` writes. `AGENTS.md` and the `CLAUDE.md` bridge are the required
baseline, always verified. `.mcp.json` and the per-editor files are optional:
`check` verifies one only once it is present on disk or recorded in
`.protean/dx-state.json`. A freshly scaffolded project carries only the baseline, so
it passes. A project missing the baseline fails. An editor file you never chose is
not counted as drift. Because the two share a scope, `refresh` fixes exactly what
`check` reports. `diff`, the preview, is not scoped this way: it always previews
every managed target, including a pending create for an optional file you have not
installed.

### Options

- `--path`, `-p`: The project directory to write into or check. Defaults to the
  current directory. A path that exists but is not a directory is rejected.

### Exit codes

- `0`: the command succeeded. For `check`, every target is up to date.
- `1`: for `check`, a target has drifted. For `install` and `refresh`, a managed
  region conflicts with a hand edit and was left untouched.
- `2`: a filesystem error, such as an unreadable or malformed target, an
  unreadable or corrupt `.protean/dx-state.json`, a `--path` that is not a
  directory, or a pack that cannot render.

A conflict on one file does not stop the others. `install` applies every file it
safely can, reports the conflict, and then exits non-zero.

## In CI

Wire `check` into a pipeline so a project's agent files stay in step with the
framework. It writes nothing and fails the job on drift.

```shell
protean dx check
```

## Building the Claude Code plugin

`build-plugin` renders Protean's teaching skills into a Claude Code plugin. It is
a maintainer command for the Protean repository itself, not a project verb: it
projects the packaged skills at `src/protean/dx/pack/skills/` into a committed
plugin tree that a Claude Code user can install.

It writes two manifests and the skill tree:

- `.claude-plugin/marketplace.json` at the repo root names the `proteanhq`
  marketplace and lists one plugin, `protean`, sourced from `./plugins/protean`.
- `plugins/protean/.claude-plugin/plugin.json` names the plugin and stamps it with
  the installed framework version, so a consumer can tell which version's guidance
  the skills carry.
- `plugins/protean/skills/<name>/` holds each skill's `SKILL.md` and any `assets/`
  and `references/`, copied byte for byte from the pack.

This cut carries skills only: no commands, agents, or hooks, and the MCP server
registration stays with the `.mcp.json` file that `install` writes.

```shell
protean dx build-plugin           # write (or regenerate) the committed tree
protean dx build-plugin --check   # exit non-zero when the tree has drifted; write nothing
```

The bare verb writes the tree so it matches the render exactly, pruning any file a
removed skill left behind. `--check` is the drift guard: it re-renders in memory,
compares byte for byte against the committed tree, writes nothing, and exits `1`
when a file is missing, stale, or orphaned. The framework version in `plugin.json`
moves with a release (through a `.bumpversion.toml` entry), so the committed tree
stays in step and the drift check does not fail on a version bump.

### Installing it in Claude Code

A Claude Code user adds the marketplace from the repository and installs the
plugin:

```shell
/plugin marketplace add proteanhq/protean
/plugin install protean@proteanhq
```

Installing the plugin makes the bundled skills available in Claude Code.
