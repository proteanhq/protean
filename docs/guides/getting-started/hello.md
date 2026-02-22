# Hello, Protean!

Define an aggregate, save it, load it — in under 20 lines of Python.

## Prerequisites

- Python 3.11+
- Protean installed ([Installation](./installation.md))

## The Code

Create a file called `hello.py`:

```python
{! docs_src/guides/getting-started/hello.py !}
```

Run it:

```shell
$ python hello.py
Created: Buy groceries (done=False)
Loaded:  Buy groceries (done=False)
ID:      5eb04301-f191-4bca-9e49-8e5a948f07f6
```

The ID will differ on your machine — Protean generates a unique identifier
for every aggregate instance automatically.

## What Just Happened?

Three things:

1. **You defined an aggregate.** `Task` is a domain concept — a cluster
   of data and rules treated as a single unit. The `@domain.aggregate`
   decorator registers it with the domain.

2. **You saved it.** `repository_for(Task)` gives you a repository — a
   persistence abstraction. The default in-memory adapter stores everything
   in a dictionary. No database required.

3. **You loaded it back.** `repo.get(task.id)` retrieves the task by its
   auto-generated ID. Everything round-trips cleanly.

All of this ran in-memory. No database, no configuration, no boilerplate.
When you are ready for a real database, you swap in an adapter through
[configuration](../../reference/configuration/index.md) — your domain code
stays exactly the same.

## Next Steps

Ready for more? The [Quickstart](./quickstart.md) builds a complete domain
with commands, events, and handlers in 5 minutes.

Or dive into the [Tutorial](./tutorial/index.md) for a guided,
chapter-by-chapter journey from aggregates to production.

<!-- test -->
