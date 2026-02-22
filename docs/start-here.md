# Start Here

A guided reading order through Protean's documentation. Follow the sections
below from top to bottom, or jump to the topic you need.

## Installation

Get Protean up and running. The
[Installation guide](./guides/getting-started/installation.md) walks you
through setting up Python, creating a virtual environment, and installing
Protean.

## Quickstart

Want to see Protean in action right away? The
[Quickstart](./guides/getting-started/quickstart.md) builds a working domain
in 5 minutes — an aggregate, a command, an event, and handlers — all running
in-memory with zero infrastructure.

## Tutorial

For a guided, end-to-end learning experience, work through
[Building Bookshelf](./guides/getting-started/tutorial/index.md) — a 10-part
tutorial that takes you from your first aggregate to a fully tested
application with a real database. It covers:

- **Part I** — Aggregates, fields, value objects, entities, and business rules
- **Part II** — Commands, domain events, and event handlers
- **Part III** — Projections and real database persistence
- **Part IV** — Testing strategies and next steps

## Core concepts

Get to know the driving principles and core ideas that shape this framework
in [Philosophy](./concepts/philosophy/index.md). In
[Domain Elements](./concepts/building-blocks/index.md), explore key DDD
elements like Aggregates, Repositories, Events, and more to understand the
core structures of Protean.

## Building with Protean

Everything you need to know to build ambitious applications with Protean is in
the [Guides](./guides/index.md) section.

Protean supports three architectural approaches — **DDD**, **CQRS**, and
**Event Sourcing** — each building on the one before it. Start with DDD
and evolve later. See [Choose a Path](./guides/pathways/index.md) to
compare the options.

Within the guides, you'll find everything from crafting rich
[domain models](./guides/compose-a-domain/index.md) to adding
[behavior and business rules](./guides/domain-behavior/index.md), wiring up
[commands and handlers](./guides/change-state/index.md), and reacting to
state changes with [event handlers and projections](./guides/consume-state/index.md).

## Finding your way around

If you know what you want to do but aren't sure where to look, start here:

- **[How Do I...?](./how-do-i.md)** — A task-oriented index. Look up what
  you're trying to accomplish and jump straight to the right guide.
- **[Contents](./contents.md)** — A flat, searchable listing of every page in
  the documentation.

## Configuration and infrastructure

Protean uses a simple configuration file (`domain.toml`) to wire in databases,
brokers, caches, and other infrastructure without changing domain code. See
[Configuration](./reference/configuration/index.md) for details.

For infrastructure adapters — PostgreSQL, Elasticsearch, Redis, MessageDB, and
more — see [Adapters](./reference/adapters/index.md).

## Async processing

The Protean [Server](./concepts/async-processing/index.md) is an async engine that
processes events, commands, and external messages in the background. It
supports the [outbox pattern](./concepts/async-processing/outbox.md) for reliable
delivery and includes built-in [observability](./reference/server/observability.md).

## CLI

The `protean` command-line tool helps you scaffold projects, run the server,
manage databases, and more. See [CLI](./reference/cli/index.md) for the full
list of commands.

## Testing

Protean provides pytest fixtures and a layered testing strategy — from fast
in-memory [domain model tests](./guides/testing/domain-model-tests.md) to
full [integration tests](./guides/testing/integration-tests.md) with real
infrastructure. See [Testing](./guides/testing/index.md).

## Patterns and best practices

Looking for architectural guidance? The
[Patterns](./patterns/index.md) section covers recurring design patterns —
aggregate sizing, idempotent handlers, validation layering, event versioning,
and more.

## Glossary

Stuck on a term? There is a comprehensive [Glossary](glossary.md) to help you
find clear definitions for all the concepts and jargon you'll encounter as you
navigate Protean.

## Community

You're not alone on this journey. Join our
[Community](./community/index.md) to connect with fellow Protean users, share
experiences, and get your questions answered. Together, we can make Protean
even better!
