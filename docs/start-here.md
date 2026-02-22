# Start Here

Welcome to Protean! Whether you're a seasoned developer or new to the
framework, this guide will help you navigate the documentation and get started
on the right foot.

## Installation

The first step is to get Protean up and running on your system. The
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
[Building Bookshelf](./guides/getting-started/tutorial/index.md) — a 15-part
tutorial that takes you from your first aggregate to event sourcing and
testing. It covers the full breadth of Protean:

- **Part I** — Your first aggregate, fields, and identity
- **Part II** — Value objects, entities, associations, and business rules
- **Part III** — Commands, domain events, and event handlers
- **Part IV** — Application services, domain services, and projections
- **Part V** — Persistence, async processing, and event sourcing
- **Part VI** — Testing strategies

## Core concepts

Get to know the driving principles and core ideas that shape this framework
in [Philosophy](./core-concepts/philosophy.md). In
[Domain Elements](./core-concepts/domain-elements/index.md), explore key DDD
elements like Aggregates, Repositories, Events, and more to understand the
core structures of Protean.

## Building with Protean

Everything you need to know to build ambitious applications with Protean is in
the [Guides](./guides/index.md) section.

Protean supports three architectural approaches, each building on the one
before it:

- **[Domain-Driven Design](./guides/pathways/ddd.md)** — Model your domain
  with application services, repositories, and events. The simplest way to
  start.
- **[CQRS](./guides/pathways/cqrs.md)** — Separate reads from writes with
  commands, command handlers, and projections.
- **[Event Sourcing](./guides/pathways/event-sourcing.md)** — Derive state
  from event replay for full audit trails and temporal queries.

Not sure which to pick? Start with DDD — you can evolve later. See
[Choose a Path](./guides/pathways/index.md) for guidance.

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
[Configuration](./guides/essentials/configuration.md) for details.

For infrastructure adapters — PostgreSQL, Elasticsearch, Redis, MessageDB, and
more — see [Adapters](./adapters/index.md).

## Async processing

The Protean [Server](./guides/server/index.md) is an async engine that
processes events, commands, and external messages in the background. It
supports the [outbox pattern](./guides/server/outbox.md) for reliable
delivery and includes built-in [observability](./guides/server/observability.md).

## CLI

The `protean` command-line tool helps you scaffold projects, run the server,
manage databases, and more. See [CLI](./guides/cli/index.md) for the full
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
