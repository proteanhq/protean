# `protean add`

The `protean add` command previews the files a new element slice would add to
your project. It computes a change plan and prints it. It writes nothing: this is
a read-only preview.

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
- `--help`: Show the help message and exit.

## What it plans

For `aggregate`, `add` plans one complete write-side vertical slice under
`src/<package>/<slug>/`, one concept per module:

- `__init__.py`: a docstring only, so the package initializer stays side-effect
  free (see [ADR-0030](../../../adr/0030-canonical-project-layout.md)).
- `aggregate.py`: the aggregate with a `create` factory that raises the created
  event.
- `commands.py`: the `Create<Name>` command.
- `events.py`: the `<Name>Created` event.
- `command_handlers.py`: the handler that creates the aggregate and adds it to
  its repository.

The slice sits exactly one directory below the domain root, so
`domain.init(traverse=True)` discovers and registers it.

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

Preview the `Order` aggregate slice in the current project:

```shell
protean add aggregate Order
```

Point at another project directory:

```shell
protean add aggregate Order --path ./my-project
```

## Exit codes

- `0`: the plan was computed and printed.
- `2`: a usage error. Any of:
  - an unsupported element type (only `aggregate` is supported today);
  - an invalid name. It is invalid if it is not a Python identifier, if it has
    no words in it (`_`), or if the class name and slug it derives are a Python
    keyword or not valid Python names. Each of those would produce a slice that
    does not compile;
  - a project the planner could not resolve: no `src/` directory, no
    `src/<package>/domain.py`, more than one such file, a `domain.py` that does
    not parse, or a `domain.py` that constructs no `Domain`.

## What it does not do

`add` writes nothing. It only previews the plan. Applying the plan (creating the
files on disk) is a separate step, added in a later release.
