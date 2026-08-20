# `protean add`

The `protean add` command scaffolds a new element slice into your project. It
computes a change plan and, by default, writes the files. Pass `--dry-run` to
preview the plan without writing anything.

Apply is create-only and all-or-nothing. If any target file already exists, or a
write fails partway, `add` changes nothing and exits `1`.

## Usage

```shell
protean add [OPTIONS] ELEMENT_TYPE NAME
```

## Arguments

| Argument       | Description                                        | Default | Required |
|----------------|----------------------------------------------------|---------|----------|
| `ELEMENT_TYPE` | The element type to add. Only `aggregate` for now. | None    | Yes      |
| `NAME`         | The aggregate name, e.g. `Order`.                  | None    | Yes      |

## Options

- `--path`, `-p`: Project directory to plan against. Defaults to the current
  directory.
- `--dry-run`: Preview the plan without writing anything.
- `--apply`: Write the plan to disk. This is the default, so the flag is only
  useful to be explicit. It cannot be combined with `--dry-run`.
- `--help`: Show the help message and exit.

## What it plans

For `aggregate`, `add` plans one complete vertical slice under
`src/<package>/<slug>/`, one concept per module:

- `__init__.py`: a docstring only, so the package initializer stays side-effect
  free (see [ADR-0030](../../../adr/0030-canonical-project-layout.md)).
- `aggregate_base.py`: the generated base, `class <Name>Base(BaseAggregate)`,
  carrying the fields and a `create` factory that raises the created event.
- `aggregate.py`: the hand-owned subclass,
  `@domain.aggregate class <Name>(<Name>Base)`, where you add invariants and
  behavior.
- `commands.py`: the `Create<Name>` command.
- `events.py`: the `<Name>Created` event.
- `command_handlers.py`: the handler that creates the aggregate and adds it to
  its repository.
- `projection.py`: a `<Name>Summary` read-model projection.
- `projectors.py`: the projector that builds `<Name>Summary` from
  `<Name>Created`.

The projector consumes the created event, so the applied slice passes `protean
verify` (an event with no consumer would trip the framework's `UNHANDLED_EVENT`
check). The slice sits exactly one directory below the domain root, so
`domain.init(traverse=True)` discovers and registers it.

### The generation-gap seam

The aggregate is split across two files so a later re-run of `add` cannot clobber
your own code (see
[ADR-0035](../../../adr/0035-generation-gap-seam.md)). The generated base
(`aggregate_base.py`) holds the structure and wiring, and `add` refreshes it on
every re-run. The hand-owned subclass (`aggregate.py`) holds your invariants and
behavior, and `add` writes it once and never overwrites it. Every planned file
records an `ownership` marker, `generated` or `hand_owned`; the preview shows it
next to each path (as `generated` or `hand-owned`), so you can see which files a
re-run would refresh and which it would leave alone. `add` still only previews
the plan today; the applier that honors the marker on disk comes in a later
release.

## How the name is used

`add` splits `NAME` into words on underscores and on case changes, then builds
two things from them: the class name is the PascalCase join, and the slug (the
directory name, the local variable, and the id-field prefix) is the snake_case
one. So `OrderItem`, `orderItem` and `order_item` all plan the same slice:
`class OrderItem` in `src/<package>/order_item/`.

A run of capitals counts as one word, so `HTTPServer` stays `HTTPServer` and its
slug is `http_server`.

The project is resolved from `src/<package>/domain.py`. `add` reads the package
name and the domain variable (the name your `@domain.aggregate` decorators use)
straight from that file, without importing it.

## Examples

Write the `Order` aggregate slice into the current project:

```shell
protean add aggregate Order
```

Preview the plan first, without writing anything:

```shell
protean add aggregate Order --dry-run
```

Point at another project directory:

```shell
protean add aggregate Order --path ./my-project
```

## Exit codes

- `0`: the slice was applied (or, with `--dry-run`, the plan was printed).
- `1`: an apply failure. Either a target file already exists (`add` refuses to
  overwrite it), or a write failed partway. On a partway failure the applier
  rolls the tree back to its pre-apply state, so a failed `add` never leaves a
  half-written slice. To re-apply into a project that already has the slice,
  remove the existing files first.
- `2`: a usage error. Any of:
  - `--dry-run` and `--apply` together (they contradict each other);
  - an unsupported element type (only `aggregate` is supported today);
  - an invalid name. It is invalid if it is not a Python identifier, if it has
    no words in it (`_`), or if the class name and slug it derives are a Python
    keyword or not valid Python names. Each of those would produce a slice that
    does not compile;
  - a project the planner could not resolve: no `src/` directory, no
    `src/<package>/domain.py`, more than one such file, a `domain.py` that does
    not parse, or a `domain.py` that constructs no `Domain`.

## Apply is create-only and all-or-nothing

`add` only creates files; it never edits an existing one. Before writing, it
checks every target: if any already exists, it writes nothing and exits `1`,
rather than overwrite your code. If a write fails partway through, it deletes the
files it wrote and removes the directories it created, then exits `1`, leaving the
project exactly as it was. So after a successful `add`, `protean verify` is
green; after a failed one, nothing changed.
