# Giving an Agent Domain Context

A coding agent working on your project needs to know your domain: the aggregate
clusters, the commands and events, the handlers, the projections. There are two
ways to give it that knowledge. This guide explains both and tells you which to
reach for first.

## Use the MCP server first

The [`protean mcp`](../reference/cli/runtime/mcp.md) server is the recommended
way. It exposes Protean's operations as tools an agent calls: `validate`,
`check`, `introspect`, `explain`, and `scaffold`. Every tool answers live from
the installed domain, so the agent always reasons about the code that is
actually there, at the version of Protean the project actually runs.

Because the answers come from the domain itself, there is no copy to
regenerate and commit, and no refresh step in your build. One thing to know:
the server imports your domain modules on the first call and Python holds them
in memory for the life of that process, so a server that is already running
keeps answering from the version it imported. Restart it after you change the
source, and the next `introspect` reflects the change.

Register the server in a `.mcp.json` file and point your agent at it. The
[`protean mcp` reference](../reference/cli/runtime/mcp.md) covers installation,
transports, and registration.

## When a committed snapshot makes sense

Some agents do not speak MCP. For those, a committed `llms.txt` snapshot is a
legitimate fallback. `protean docs generate --type=llms --domain=my_app` renders
a context pack from the domain's Intermediate Representation: the aggregate
clusters with their commands, events, and handlers, and the projections. You
commit that file, and the agent reads it like any other file in the repository.

Know the trade-off before you choose this path. A committed file is a copy. It
was true when you generated it, and it goes stale the moment the domain moves
ahead of it. The MCP server does not have this problem, because it never holds a
copy. So use the snapshot only when the agent cannot use MCP, and put a drift
check in place so a stale file does not pass unnoticed.

## Keeping the snapshot fresh

`protean docs generate --type=llms --check` is the drift check. It renders the
snapshot fresh in memory, compares it byte for byte to the committed file,
writes nothing, and exits non-zero when they differ. A missing file counts as
drift. The exit codes match `protean dx check`: `0` when the file is up to date,
`1` on drift.

Set the snapshot path and the domain once, so neither command repeats the flags:

```toml
# pyproject.toml
[tool.protean.docs]
domain_snapshot = { path = "llms.txt", domain = "my_app" }
```

Then regenerate with `protean docs generate --type=llms` and check with
`protean docs generate --type=llms --check`.

The path is read relative to the file that declares it, so both commands name
the same snapshot from every directory that finds the config. The command looks
in the directory you run it from and its two parents, so keep the key in a
config file at the project root and run from the root or at most two levels
below it.

### A pre-commit recipe

To fail a commit when the snapshot is stale, wire the check as a local
[pre-commit](https://pre-commit.com) hook. This is a recipe you choose to add;
nothing installs it for you.

```yaml
# .pre-commit-config.yaml
repos:
  - repo: local
    hooks:
      - id: protean-llms-snapshot
        name: llms.txt is up to date
        entry: protean docs generate --type=llms --check
        language: system
        pass_filenames: false
```

### A CI recipe

To fail a build when the snapshot is stale, run the same check as a CI step. It
exits non-zero on drift, so the job fails on its own.

```yaml
# in your CI workflow
- name: Check llms.txt is up to date
  run: protean docs generate --type=llms --check
```

Neither recipe is installed by `protean new` or `protean dx`. You add the one
you want, when you want it.
