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
- `--annotations`: Path to an annotations TOML file (only with
  `--type=event-model`). Defaults to `.protean/annotations.toml` when present.
  See [Annotating the event model](#annotating-the-event-model).

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

In Markdown output each slice leads with a structural Given-When-Then before
the diagram:

- **Given** the aggregate the slice is about.
- **When** the cluster's commands (the triggers).
- **Then** the cluster's non-fact events (the results).

The GWT is derived structurally from the IR. It is slice-level: a slice with
several commands or events lists them all on the When and Then lines rather
than pairing each command with the event it produces. Commands-only or
events-only slices drop the line they have nothing for. This GWT is a
Markdown-only lead; the `--format=mermaid` output stays a bare flowchart.

```shell
# One combined flowchart of all slices
protean docs generate --domain=my_app --type=event-model --format=mermaid

# One GWT-led diagram per slice, as Markdown
protean docs generate --domain=my_app --type=event-model
```

Unlike the other diagram types, `event-model` is its own view and is not
included in `--type=all`.

### Annotating the event model

The event model carries structure, not the business context a person adds: why
a slice exists, the rule behind it, which team owns it. Those notes live outside
the generated output, in `.protean/annotations.toml`, and merge back in on
render. Keeping them out of the diagram means the model stays disposable and the
notes stay under version control next to the code they describe. The file's
shape is recorded in [ADR-0032](../../../adr/0032-annotation-file-for-the-event-model.md).

The file has a top-level `[annotations]` map keyed by element FQN. Each entry
carries a required `note` (free text, the business context) and an optional
`owner` (the team or person accountable). The FQN is the value
`protean.utils.fqn` computes, `module.QualifiedName`; in a project generated
from the canonical layout, an `Order` aggregate in
`src/myproj/example/aggregate.py` has the FQN `myproj.example.aggregate.Order`.
The FQN must be quoted, because TOML reads its dots as table separators
otherwise:

```toml
[annotations."myproj.example.aggregate.Order"]
note = """
Orders are the fulfillment boundary. An order cannot ship until payment
clears, so PaymentConfirmed gates the shipment slice.
"""
owner = "Fulfillment"
```

On render, each note merges into the slice for the element it keys. A note on
an aggregate, a command, an event, or a consumer drawn in a slice (a projector,
event handler, or process manager) shows after that slice's Given-When-Then and
before its diagram. Because the key is the element's FQN, a note stays attached
across a content change (adding a field, reordering elements, regenerating the
model) and breaks on an identity change (renaming or moving the element), which
changes the FQN.

A key that matches no drawn element is listed in an "Unmatched annotations"
section at the end of the render, so a note orphaned by a rename or a typo stays
visible and gets re-keyed. A fact event is filtered from the event model, so it
draws no node; a note keyed to one is reported unmatched.

`--annotations <path>` reads the file from a non-default location. An explicit
path that does not exist is an error, as is a malformed file: either aborts the
command before any output is written. With no annotations file present, the
default path absent and no `--annotations` given, the render is exactly what it
is without the feature.

```shell
# Merge notes from the default .protean/annotations.toml
protean docs generate --domain=my_app --type=event-model

# Read notes from a non-default path
protean docs generate --domain=my_app --type=event-model \
    --annotations=docs/event-model-notes.toml
```

Notes are Markdown prose and cannot sit inside a raw flowchart, so
`--format=mermaid` leaves the diagram body unchanged and appends only the
unmatched-annotation report, the one piece that belongs at the end of the
render.

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
