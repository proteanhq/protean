# `protean docs`

The `protean docs` command group has two subcommands:

- `protean docs generate` renders architecture documentation from a domain or
  an IR JSON file.
- `protean docs preview` starts a live preview server for Protean
  documentation.

## `protean docs generate`

Generate architecture diagrams and catalogs from a domain's
[Intermediate Representation](../../../guides/compose-a-domain/inspecting-the-ir.md).

```shell
# From a live domain
protean docs generate --domain=my_app --type=events

# From an IR JSON file
protean docs generate --ir=domain-ir.json --type=event-model
```

### Options

- `--domain`, `-d`: Path to the domain module. Mutually exclusive with `--ir`.
- `--ir`: Path to an IR JSON file. Mutually exclusive with `--domain`.
- `--type`, `-t`: What to generate. One of:
    - `clusters`: aggregate cluster class diagrams.
    - `events`: command-to-event flow diagrams plus downstream consumers.
    - `handlers`: handler wiring diagrams.
    - `catalog`: an event and command catalog (Markdown tables).
    - `event-model`: the EventModeling slice timeline (see below).
    - `all` (default): every section except `event-model`.
- `--format`, `-f`: `markdown` (fenced code blocks, the default) or `mermaid`
  (raw diagram source). `mermaid` is not supported for `catalog`.
- `--output`, `-o`: Write to a file instead of stdout.
- `--cluster`: Filter to a single cluster FQN (only with `--type=clusters` or
  `--type=all`).

### The event model slice timeline

`--type=event-model` renders the domain as an
[EventModeling](https://eventmodeling.org) slice timeline. Each aggregate
cluster becomes one slice that reads left to right:

1. **Command(s)** that trigger the aggregate.
2. **Aggregate (state)** that decides and holds state.
3. **Event(s)** the aggregate raises (fact events are omitted).
4. **Read models and automations** that consume those events. Projectors are
   read models, drawn as cylinders. Event handlers and process managers are
   automations, drawn as hexagons, so a read model and an automation are told
   apart at a glance. A process manager also shows its `start`/`end`
   lifecycle, both in its node label and on the edge from the event.

Consumers are matched to a slice's events by the event type, so the whole
diagram is derived from the IR alone.

```shell
# One combined flowchart of all slices
protean docs generate --domain=my_app --type=event-model --format=mermaid

# One titled diagram per slice, as Markdown
protean docs generate --domain=my_app --type=event-model
```

Unlike the other diagram types, `event-model` is its own view and is not
included in `--type=all`.

## `protean docs preview`

The `protean docs preview` command starts a live preview server for Protean
documentation. This allows you to view changes in real-time as you edit.

### Usage

```shell
protean docs preview [OPTIONS]
```

### Options

- `--help`: Shows the help message and exits.

### Running a Preview Server

To start the live preview server for your project's documentation, run
the command without any additional options:

```shell
protean docs preview`
```

This will start a local server, usually accessible via a web browser at a URL
such as `http://localhost:8000`. The exact URL will be displayed in your
command line interface once the server is running:

```shell
INFO    -  Building documentation...
INFO    -  Cleaning site directory
INFO    -  Documentation built in 0.56 seconds
INFO    -  [09:45:08] Watching paths for changes: 'docs', 'mkdocs.yml'
INFO    -  [09:45:08] Serving on http://127.0.0.1:8000/
```
