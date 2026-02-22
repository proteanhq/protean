# Chapter 5: Commands and Handlers

In this chapter we will add an `AddBook` command and a handler that
processes it, so books are added through a formal command interface
instead of direct aggregate creation.

## Defining a Command

So far we have created aggregates directly. In a real application, state
changes arrive as **commands** — formal requests to do something, named
with imperative verbs:

```python
{! docs_src/guides/getting-started/tutorial/ch05.py [ln:25-36] !}
```

A command is an immutable data object — it carries the intent ("add this
book") and the data needed to fulfill it.

## The Command Handler

A **command handler** receives the command and orchestrates the state
change:

```python
{! docs_src/guides/getting-started/tutorial/ch05.py [ln:39-58] !}
```

Notice the pattern: receive command, create aggregate, persist it, return
the result. Each handler method runs in a transaction automatically.

## Dispatching Commands

To dispatch a command, use `domain.process()`:

```python
{! docs_src/guides/getting-started/tutorial/ch05.py [ln:64-76] !}
```

We set `command_processing = "sync"` so commands are processed
immediately and `domain.process()` returns the handler's result.

Run it:

```shell
$ python bookshelf.py
Book added with ID: a3b2c1d0-...
Retrieved: The Great Gatsby by F. Scott Fitzgerald
Price: $12.99 USD

Total books: 2
  - The Great Gatsby
  - Brave New World

All checks passed!
```

Notice that we never touched the repository directly — the command
handler did that for us. This separation means the same command can
later be processed asynchronously by a background server.

## What We Built

- An **`AddBook` command** — an immutable intent object.
- A **`BookCommandHandler`** — receives the command, creates and persists
  the aggregate.
- **`domain.process()`** — dispatches commands to their handlers.

In the next chapter, we will add domain events and event handlers so the
system can react automatically when things happen.

## Full Source

```python
{! docs_src/guides/getting-started/tutorial/ch05.py !}
```

## Next

[Chapter 6: Events and Reactions →](06-events-and-reactions.md)
