# CLI

When you install Protean, you also get a handy command line interface - the `protean` script - in your virtualenv. Driven by [Typer](https://typer.tiangolo.com), the script gives access to commands that can help you scaffold projects, generate new code, and run background servers. The `--help` option will give more information about any commands and options.

Most commands accept a domain instance to load and initialize, prepping it for
shell access. The [`--domain`](project/discovery.md) option is used to specify how to
load the domain.

| Command                        |                                    |
| :----------------------------- | :----------------------------------|
| [`protean new`](project/new.md)        | Creating a domain                  |
| [`protean shell`](project/shell.md)    | Working with the shell             |
| [`protean server`](runtime/server.md)  | Running an async background server |
| [`protean observatory`](runtime/observatory.md) | Running the observability dashboard |
| [`protean db setup`](data/database.md)       | Create all database tables         |
| [`protean db drop`](data/database.md)        | Drop all database tables           |
| [`protean db truncate`](data/database.md)    | Delete all data, preserve schema   |
| [`protean db setup-outbox`](data/database.md)| Create only outbox tables          |
| [`protean snapshot create`](data/snapshot.md)| Create snapshots for ES aggregates |
| [`protean projection rebuild`](data/projection.md) | Rebuild projections from events |
| [`protean events read`](data/events.md)     | Read and display events from a stream |
| [`protean events stats`](data/events.md)    | Show stream statistics across the domain |
| [`protean events search`](data/events.md)   | Search for events by type |
| [`protean events history`](data/events.md)  | Display aggregate event timeline |

!!! note

    **Developing Protean:** There are a few additional commands to help you if you
    want to contribute to Protean.

    | Command                        |                                    |
    | :----------------------------- | :----------------------------------|
    | [`protean docs`](project/docs.md)      | Documentation helpers              |
    | [`protean test`](../../community/contributing/testing.md) | Framework test runner |
