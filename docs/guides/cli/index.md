# CLI

When you install Protean, you also get a handy command line interface - the `protean` script - in your virtualenv. Driven by [Typer](https://typer.tiangolo.com), the script gives access to commands that can help you scaffold projects, generate new code, and run background servers. The `--help` option will give more information about any commands and options.

Most commands accept a domain instance to load and initialize, prepping it for
shell access. The [`--domain`](discovery.md) option is used to specify how to
load the domain.

| Command                        |                                    |
| :----------------------------- | :----------------------------------|
| [`protean new`](new.md)        | Creating a domain                  |
| [`protean shell`](shell.md)    | Working with the shell             |
| [`protean server`](server.md)  | Running an async background server |

!!! note

    **Developing Protean:** There are a few additional commands to help you if you
    want to contribute to Protean.

    | Command                        |                                    |
    | :----------------------------- | :----------------------------------|
    | [`protean docs`](docs.md)      | Documentation helpers              |
    | [`protean test`](test.md)      | Testing helpers                    |
