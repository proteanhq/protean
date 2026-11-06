# `protean mcp`

The `mcp` command runs a [Model Context
Protocol](https://modelcontextprotocol.io) server. The server exposes Protean's
framework operations as tools a coding agent can call. Every tool answers from
the installed framework. An agent therefore always reasons about the version of
Protean the project actually runs, and never about a stale copy of the docs.

The server exposes five tools:

- `validate`: does the domain load and pass validation? A go/no-go check.
- `check`: the full diagnostic report over the domain.
- `introspect`: the domain's Intermediate Representation (its complete topology).
- `explain`: what a diagnostic code means and how to fix it.
- `scaffold`: preview a new element slice, and write it only on consent.

## Install the `mcp` extra

The server needs the optional `mcp` extra:

```shell
pip install "protean[mcp]"
```

Running `protean mcp` without the extra prints an install hint and exits, the
same way the other optional commands do. `import protean` never needs the extra.

## Run the command

```shell
protean mcp [OPTIONS]
```

## Which options does `protean mcp` take?

| Option        | Description                          | Default     |
|---------------|--------------------------------------|-------------|
| `--http`      | Serve over streamable HTTP instead of stdio. | `--no-http` |
| `--host`      | Host to bind for `--http`. Loopback by default; see [Security](#security). | `127.0.0.1` |
| `--port`      | Port to bind for `--http`.           | `8000`      |
| `--help`      | Show the help message and exit.      |             |

## Choose a transport

The server runs on stdio by default, so an MCP client can launch it directly as
a subprocess. Pass `--http` to serve over streamable HTTP instead:

```shell
protean mcp --http --host 127.0.0.1 --port 8000
```

## Registering the server

An MCP client discovers the server from a `.mcp.json` file in the project:

```json
{
  "mcpServers": {
    "protean": {
      "command": "protean",
      "args": ["mcp"]
    }
  }
}
```

Run [`protean dx install`](../project/dx.md) to write the `mcpServers.protean`
entry above into `.mcp.json` for you. `protean dx install` writes only the
`mcpServers.protean` key-path, so every other server in an existing `.mcp.json`
stays as you configured it. You can also create the file by hand as shown, or
point your client at the `.mcp.json` shipped at the root of the Protean
repository. That `.mcp.json` carries the same entry.

## What does each tool do?

### `validate`

Runs the domain's validation and returns a pass/fail verdict.

- **Input**: `domain` (optional) is the domain module path. When omitted, the
  domain is discovered from the working directory, the same way `protean check`
  discovers it.
- **Output**: `domain`, `valid` (true when there are no errors), `status`,
  `errors`, and `counts`.

### `check`

Runs the full diagnostic report, the same one `protean check` prints.

- **Input**: `domain` (optional), as above.
- **Output**: the check report: `domain`, `status`, `errors`, `diagnostics`, and
  `counts`.

### `introspect`

Returns the domain's Intermediate Representation.

- **Input**: `domain` (optional), as above. The domain is initialised before the
  IR is built.
- **Output**: the IR dict (elements, contracts, flows, clusters, and more).

### `explain`

Explains one diagnostic code from the diagnostics registry.

- **Input**: `code`, a diagnostic code such as `UNHANDLED_EVENT`.
- **Output**: the `code` and its `category`, `level`, `meaning`, `rationale`,
  `fix`, `kind`, `resolution` (the command that clears it, when one exists), and
  `teaching_skills` (the DX-pack skills that teach the code, `[]` when none do).
  An unknown code returns an error naming the closest known codes.

### `scaffold`

Plans a new element slice, and writes it only on consent.

- **Input**: `element` (the element type, `aggregate` for now), `name` (the
  element name, e.g. `Order`), `project` (optional project root, defaulting to
  the working directory), and `apply` (defaults to `false`).
- **Output**: always `applied`, `element`, and `name`. With `apply=false` (the
  default), the output also holds the rendered `preview`, the structured
  `plan`, and the list of `files` that would be created. In this mode the tool
  touches nothing. With `apply=true`, the same plus `written`, the paths it
  created.

The write only happens when the tool is called with `apply=true`. MCP clients
typically show you a tool call's arguments to approve before the call runs.
Your approval of `apply=true` is therefore your explicit consent to write.

## Security

The `scaffold` tool can write files into your project when called with
`apply=true`. Approve those calls the way your MCP client presents them. Keep
the server on stdio (or loopback for `--http`) unless you have a specific
reason to expose it. The `--http` transport is unauthenticated, so bind a
non-loopback address only on a trusted network behind an authenticating proxy.
