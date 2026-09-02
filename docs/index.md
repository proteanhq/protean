<div class="pt-home-brand">
  <img class="pt-home-brand__mark pt-home-brand__mark--light" src="./assets/protean-mark-light.svg" alt="Protean" width="48" height="48">
  <img class="pt-home-brand__mark pt-home-brand__mark--dark" src="./assets/protean-mark-dark.svg" alt="" width="48" height="48" aria-hidden="true">
  <span class="pt-home-brand__word">Protean</span>
</div>

# Your whiteboard, shipped.

[![Python](https://img.shields.io/pypi/pyversions/protean?label=Python)](https://github.com/proteanhq/protean/)
[![Release](https://img.shields.io/pypi/v/protean?label=Release)](https://pypi.org/project/protean/)
[![Build Status](https://github.com/proteanhq/protean/actions/workflows/ci.yml/badge.svg)](https://github.com/proteanhq/protean/actions/workflows/ci.yml)
[![Coverage](https://codecov.io/gh/proteanhq/protean/graph/badge.svg?token=0sFuFdLBOx)](https://codecov.io/gh/proteanhq/protean)
[![Tests](https://img.shields.io/badge/tests-12%2C000%2B-brightgreen)](community/quality.md)
[![Maintainability](https://img.shields.io/badge/maintainability-A-brightgreen)](https://docs.proteanhq.com/community/quality/)

Protean is a Python framework for domain-driven systems. You sketch aggregates,
events, and bounded contexts on a whiteboard, then write them in Python as you
drew them.

Start with plain domain-driven design, move to CQRS or event sourcing where you
need it, and change infrastructure through configuration.

It is built for **ambitious systems**: the ones whose shape you can't fully see
on day one, and that have to grow safely instead of being rewritten.

**Your domain model is the architecture.**

[Ship the Whiteboard](./guides/getting-started/hello.md){ .md-button .md-button--primary }
[Tutorial](./guides/getting-started/tutorial/index.md){ .md-button }
[Why Protean?](./why-protean.md){ .md-button }
[How Do I...?](./how-do-i.md){ .md-button }

---

## Why Protean?

<div class="grid cards" markdown>

- __:material-magnify-scan: Domain compiler__

    ---

    Your domain model is a machine-readable specification. Protean builds an
    Intermediate Representation of it, which other tools read to derive docs,
    API specs, contracts, and visual exploration.

- __:material-shield-check-outline: Always-valid domain__

    ---

    Domain objects are always valid, or they don't exist. Four layers of
    validation run on every change: field constraints, value object invariants,
    aggregate rules, and handler guards.

- __:material-call-split: Progressive architecture__

    ---

    Start with domain-driven design, move to CQRS, adopt event sourcing, all
    within the same framework. You can mix patterns per aggregate.

- __:material-power-plug-battery-outline: Infrastructure portability__

    ---

    Start with in-memory adapters, so there is no database, broker, or setup to
    deal with. When you're ready, change `domain.toml` to point at PostgreSQL,
    Redis, Elasticsearch, or MessageDB. Your domain code stays as it is.

</div>

[:material-arrow-right-box: Read more about why Protean exists](./why-protean.md){ .md-button }

---

## See it in action

```python
from protean import Domain, handle
from protean.fields import Identifier, String, Text
from protean.utils.globals import current_domain

domain = Domain() # (1)!

@domain.aggregate # (2)!
class Post:
    title: String(max_length=100, required=True)
    body: Text(required=True)
    status: String(max_length=20, default="DRAFT")

    def publish(self):
        self.status = "PUBLISHED"
        self.raise_(PostPublished(post_id=self.id, title=self.title)) # (3)!

@domain.event(part_of="Post") # (4)!
class PostPublished:
    post_id: Identifier(required=True)
    title: String(required=True)

@domain.command(part_of="Post") # (5)!
class CreatePost:
    title: String(max_length=100, required=True)
    body: Text(required=True)

@domain.command_handler(part_of=Post) # (6)!
class PostCommandHandler:
    @handle(CreatePost)
    def create_post(self, command: CreatePost):
        post = Post(title=command.title, body=command.body)
        current_domain.repository_for(Post).add(post) # (7)!
        return post.id
```

1. :material-domain: **Domain.** The central registry that wires all elements together.
2. :material-cube-outline: **Aggregate.** The core building block, holding fields and business logic.
3. :material-bell-ring-outline: **Raising an event.** `raise_()` emits a domain event to notify the rest of the system.
4. :material-lightning-bolt: **Event.** An immutable record of something that happened in the domain.
5. :material-play-circle-outline: **Command.** An intent to change state, carrying the data needed to do it.
6. :material-cog-outline: **Command handler.** Receives a command, creates or updates aggregates, and persists them.
7. :material-database-outline: **Repository.** The built-in persistence layer for adding, getting, and removing aggregates without touching the database directly.

Aggregates, commands, events, and handlers are all pure Python, with decorators
that wire them together. You need no infrastructure to get started.

---

## Choose your path

Protean supports three architectural approaches, and each builds on the one
before it. Start simple and add sophistication as your needs change.

| | Path | Best for |
|---|---|---|
| :material-shield-outline: | [**Domain-Driven Design**](./guides/pathways/ddd.md) | Clean domain modeling, and the simplest way to start |
| :material-call-split: | [**CQRS**](./guides/pathways/cqrs.md) | Separating reads from writes with commands and projections |
| :material-history: | [**Event Sourcing**](./guides/pathways/event-sourcing.md) | A full audit trail, temporal queries, and event replay |

If you have no strong reason to choose, start with domain-driven design and
evolve later. [Choose a path](./guides/pathways/index.md) compares them in
detail.

To work out whether Protean suits your system at all, the
[Applicability Charter](./reference/applicability.md) states plainly what it is
built for, and the shapes of systems it is not.

---

## Built to last

<div class="grid cards" markdown>

- __:material-test-tube: 12,000+ tests__

    ---

    About three lines of test per line of code. Every commit runs against
    PostgreSQL, Redis, Elasticsearch, MessageDB, and SQL Server.

- __:material-check-decagram: Zero lint violations__

    ---

    Clean Ruff linting and formatting, enforced on every commit through
    pre-commit hooks.

- __:material-chart-line: A-grade maintainability__

    ---

    95% of source files score in the highest maintainability tier, at an average
    cyclomatic complexity of 3.38.

- __:material-puzzle-outline: 12 adapters, 4 ports__

    ---

    Pluggable infrastructure across databases, brokers, event stores, and
    caches, tested on five Python versions.

</div>

[:material-arrow-right-box: Full quality report](./community/quality.md){ .md-button }

---

## Explore the documentation

<div class="grid cards" markdown>

-   __:material-hand-wave-outline: Hello, Protean!__

    ---

    Define, save, and load your first aggregate in under 20 lines.

    [:material-arrow-right-box: Hello, Protean!](./guides/getting-started/hello.md)

-   __:material-rocket-launch-outline: Quickstart__

    ---

    Commands, events, and handlers in 5 minutes.

    [:material-arrow-right-box: Quickstart](./guides/getting-started/quickstart.md)

-   __:material-school-outline: Tutorial__

    ---

    A 22-chapter tutorial, from your first aggregate to running in production.

    [:material-arrow-right-box: Tutorial](./guides/getting-started/tutorial/index.md)

-   __:material-magnify: How Do I...?__

    ---

    A task-oriented index. Look up what you're trying to do and go straight to
    the right guide.

    [:material-arrow-right-box: How Do I...?](./how-do-i.md)

-   __:material-book-open-page-variant-outline: Guides__

    ---

    Step-by-step instructions for every task Protean supports.

    [:material-arrow-right-box: Guides](./guides/index.md)

- __:material-lightbulb-outline: Core concepts__

    ---

    Domain-driven design, CQRS, and event sourcing explained.

    [:material-arrow-right-box: Core concepts](./concepts/architecture/ddd.md)

-   __:material-puzzle-outline: Adapters__

    ---

    PostgreSQL, SQL Server, Redis, Elasticsearch, MessageDB, and more.

    [:material-arrow-right-box: Adapters](./reference/adapters/index.md)

- __:material-flask-outline: Patterns & recipes__

    ---

    Recurring designs, with the trade-offs spelled out.

    [:material-arrow-right-box: Patterns](./patterns/index.md)

- __:material-arrow-up-bold-circle-outline: Upgrading?__

    ---

    Migration guides per version, covering required changes, behavioural
    differences, and what's new.

    [:material-arrow-right-box: Migration guides](./reference/migration/index.md)

</div>
