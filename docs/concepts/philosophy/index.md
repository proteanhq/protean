# Philosophy & Design Principles

Protean is built around a simple conviction: **your domain logic should
drive your architecture, not the other way around.** The framework is
rooted in Domain-Driven Design, pragmatic about technology, and designed
to let your application evolve alongside your business.

These principles guide every design decision in Protean.

## Mirror the Domain in Code

Your codebase should read like the business it serves — not just at the
class level, but at the folder level too. When a newcomer opens your
project, the directory tree should read like the table of contents of a
book about your business, not like the index of a framework manual.

### In Classes

Protean's domain elements — aggregates, entities, value objects, commands,
events — map directly to DDD tactical patterns, so business requirements
translate naturally into code.

Python's readability is a deliberate advantage here. Domain experts and
developers can look at the same aggregate class and have a shared
conversation about what the system does. There is no ORM inheritance to
decipher, no framework-specific base classes to learn. A `Post` aggregate
with a `publish()` method reads exactly like what it is.

### In Folder Structure

The same principle extends to how you organize files. **The folder tree
owns the "what" (domain concepts). The framework owns the "which kind"
(layer, side, boundary).**

Classic layered approaches split code into `domain/`, `application/`,
`infrastructure/` — and completely destroy domain visibility. To
understand a single feature, you fish through three separate subtrees.
Protean's decorators (`@Aggregate`, `@CommandHandler`, `@Projection`,
`@Repository`) already declare what layer each element belongs to. The
framework carries this architectural metadata so your folder structure
doesn't have to repeat it.

This means you organize by **domain concept** — aggregates as top-level
folders, capability files that colocate related commands and handlers,
projections grouped by the business question they answer. Every folder
and file should be something you'd explain to a product manager.

See the [Organize by Domain Concept](../../patterns/organize-by-domain-concept.md)
pattern for detailed structural guidance and examples.

## Prototype Rapidly, Iterate Freely

The first iteration of a model is rarely right. Effective models emerge
from exploring a problem from multiple angles and iterating on initial
ideas.

Protean ships with **in-memory adapters** for databases, brokers, caches,
and event stores out of the box. This means you can build and test your
entire domain model without installing or configuring any infrastructure.
Focus purely on getting the domain right — throw away your first model
and your second, and discover the best design through continuous
refinement.

This feedback loop is fast: write an aggregate, test it against business
scenarios, adjust, repeat. No database migrations, no broker setup, no
waiting.

## Separate Domain from Infrastructure

Technology concerns have a way of creeping into business logic. Before
long, your domain code is coupled to a specific database, your business
rules are tangled with API serialization, and changing any technology
means rewriting core logic.

Protean enforces a clean separation through the **Ports and Adapters**
(Hexagonal) architecture. Your domain model knows nothing about
databases, message brokers, or caches. Infrastructure is defined through
configuration, not code changes:

- **Databases**: PostgreSQL, Elasticsearch, or in-memory
- **Brokers**: Redis Streams, Redis Pub/Sub, or inline (synchronous)
- **Event Stores**: MessageDB or in-memory
- **Caches**: Redis or in-memory

Switching from an in-memory store to PostgreSQL is a configuration
change. Your domain logic, tests, and business rules remain untouched.
Infrastructure elements are initialized and injected at runtime, ensuring
that your core logic stays consistent across local development, CI/CD,
and production.

## Pragmatism over Purity

Real-world applications rarely fit a single architectural pattern
perfectly. Forcing CQRS everywhere leads to over-engineering some
components while under-serving others. Protean takes a **pragmatic
approach**: you can mix architectural patterns at the aggregate level
within the same domain.

One aggregate might use simple DDD with application services. Another
might need CQRS with commands and projections. A third might require
full Event Sourcing for audit trails. Protean supports all three in the
same codebase, provided the decisions are explicit and well-documented.

When the framework's defaults don't fit, Protean provides **escape
hatches** — you can override its implementation and specify your own
database models, custom repository queries, or adapter-specific
optimizations. The goal is always to serve the domain, not to enforce
architectural dogma.

## Evolve Architecture Incrementally

You don't need to decide your final architecture on day one. In early
stages of development, it's rare to clearly understand all the domains
and their boundaries. Premature decisions about these boundaries can
be detrimental as the project matures.

Protean is designed for **progressive evolution**:

- **Start with DDD** — application services, repositories, and events.
  The simplest way to build with Protean.
- **Add CQRS** when you need it — introduce commands, command handlers,
  and projections for specific aggregates.
- **Adopt Event Sourcing** where it matters — for aggregates that need
  full audit trails, temporal queries, or complex state transitions.

As your understanding deepens, you can decompose a monolithic domain
into finer-grained **bounded contexts**, extract subdomains, and evolve
your architecture without rewriting from scratch. Protean's high degree
of testability ensures these refactoring efforts happen safely, without
introducing regressions.

Technology decisions follow the same principle: **defer until the last
responsible moment.** Start with in-memory adapters, prove your domain
model works, then choose your production stack. Even after choosing,
Protean's configuration-based approach makes switching costs extremely
low.

## Communicate Through Events

As systems grow, tight coupling between subdomains creates fragility.
A change in one bounded context cascades into others, and the whole
system becomes harder to maintain.

Protean uses **events as the primary communication mechanism** between
aggregates and bounded contexts. Events represent facts — things that
happened — and are propagated across the system to keep components in
sync without direct dependencies.

This event-centric approach enables:

- **Loose coupling** between bounded contexts that evolve independently
- **State synchronization** without shared databases or direct API calls
- **Event Sourcing** where aggregate state is derived entirely from
  events — with `@apply` handlers as the single source of truth for
  state mutations during both live operations and replay
- **Async processing** via the Protean server engine for production
  workloads

## Test with Confidence

Protean's separation of domain and infrastructure makes comprehensive
testing straightforward. Because your domain model runs against in-memory
adapters by default, you can aim for **100% test coverage** of business
logic without any infrastructure setup.

The testing strategy works in layers:

- **Domain model tests** run entirely in-memory — fast, deterministic,
  and focused on business rules
- **Application tests** verify command handling, event processing, and
  service coordination
- **Integration tests** run against real databases and brokers when you
  need to verify adapter behavior

Protean comes with built-in support for `pytest` and `pytest-bdd`,
streamlining Test-Driven Development. Tests written during prototyping
remain valid when you plug in production infrastructure — because the
domain logic hasn't changed.
