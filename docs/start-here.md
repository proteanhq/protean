# Start Here

A reading order through Protean's documentation. Work down the sections, or jump
to the topic you need.

## Is Protean right for you?

The [Applicability Charter](./reference/applicability.md) states what Protean
is a good fit for. It also names the shapes of systems Protean does not fit,
with the reason in each case. It is worth reading before you invest much time.

## Install Protean

The [Installation guide](./guides/getting-started/installation.md) covers setting
up Python, creating a virtual environment, and installing Protean.

## Hello, Protean!

[Hello, Protean!](./guides/getting-started/hello.md) defines an aggregate, saves
it, and loads it back in under 20 lines. It is the fastest way to see what
Protean feels like.

## Build a domain in 5 minutes

The [Quickstart](./guides/getting-started/quickstart.md) builds a working domain
in 5 minutes: an aggregate, a command, an event, and handlers, all running in
memory with no infrastructure.

## Work through the Bookshelf tutorial

[Building Bookshelf](./guides/getting-started/tutorial/index.md) is a 22-chapter
tutorial that takes you from your first aggregate to a tested application running
against a real database. It covers:

- **Part I**: Aggregates, fields, value objects, entities, and business rules.
- **Part II**: Commands, domain events, event handlers, projections, persistence,
  project structure, an API, and testing.
- **Part III**: The async server, domain services, subscribers, and fact events.
- **Part IV**: Message tracing, dead letter queues, health monitoring, and
  priority lanes.
- **Part V**: Process managers, advanced query patterns, and how the pieces fit
  together.

## Learn event sourcing with the Fidelis tutorial

[Building Fidelis](./guides/getting-started/es-tutorial/index.md) is a 22-chapter
tutorial that builds a banking ledger with immutable audit trails, projections,
and production tooling. It assumes you have worked through Bookshelf.

## Upgrade an existing project

If you are migrating an existing project, the
[migration guides](./reference/migration/index.md) cover the required changes,
behavioural differences, and what is new in each version.

## Learn the core concepts

[Philosophy](./concepts/philosophy/index.md) covers the principles and ideas that
shape the framework. One of them is the
[always-valid guarantee](./concepts/philosophy/always-valid.md): domain objects
are validated continuously and can never exist in an invalid state. In
[Domain Elements](./concepts/building-blocks/index.md) you will find the DDD
elements Protean is built from, including aggregates, repositories, and events.

For a broader picture of what makes Protean different, see
[Why Protean?](./why-protean.md).

## Building with Protean

The [Guides](./guides/index.md) section shows how to build with Protean.

Protean supports three architectural approaches, **DDD**, **CQRS**, and **Event
Sourcing**, each building on the one before it. Start with DDD and evolve later.
[Choose a Path](./guides/pathways/index.md) compares the options.

The guides start with building rich [domain
models](./guides/compose-a-domain/index.md). They then cover adding [behaviour
and business rules](./guides/domain-behavior/index.md), writing [commands and
handlers](./guides/change-state/index.md), and reacting to state changes with
[event handlers and projections](./guides/consume-state/index.md).

## Finding your way around

When you know your task but not the page for it, use one of these:

- **[How Do I...?](./how-do-i.md)**: A task-oriented index. Look up what you are
  trying to accomplish and go straight to the right guide.
- **[Contents](./contents.md)**: A flat, searchable listing of every page in the
  documentation.

## Configure databases, brokers, and caches

Protean reads a configuration file (`domain.toml`) to connect databases,
brokers, caches, and other infrastructure without changing domain code. See
[Configuration](./reference/configuration/index.md).

For the infrastructure adapters themselves, including PostgreSQL, Elasticsearch,
Redis, and MessageDB, see [Adapters](./reference/adapters/index.md).

## Process messages in the background

The Protean [Server](./concepts/async-processing/index.md) is an async engine
that processes events, commands, and external messages in the background. It
supports the [outbox pattern](./concepts/async-processing/outbox.md) for reliable
delivery and comes with
[observability](./reference/server/observability.md) built in.

## CLI

The `protean` command-line tool scaffolds projects, runs the server, and sets
up, truncates, and drops database tables. See [CLI](./reference/cli/index.md)
for the full list of commands.

## Test your domain

Protean provides pytest fixtures and a layered testing strategy, from fast
in-memory [domain model tests](./guides/testing/domain-model-tests.md) to full
[integration tests](./guides/testing/integration-tests.md) against real
infrastructure. See [Testing](./guides/testing/index.md).

## Learn the recurring design patterns

The [Patterns](./patterns/index.md) section covers recurring designs and their
trade-offs, including aggregate sizing, idempotent handlers, validation layering,
and event versioning.

## Look up a term in the glossary

The [Glossary](glossary.md) defines the concepts and terms you will meet across
these pages.

## Ask questions and contribute

The [Community](./community/index.md) page covers where to ask questions, how to
report a problem, and how to contribute.
