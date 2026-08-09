# Philosophy & Design Principles

Protean is built on one idea: **your domain logic should drive your
architecture.** It is rooted in Domain-Driven Design, pragmatic about
technology, and built so your application can change as the business does.

These are the principles behind the design decisions.

## Mirror the Domain in Code

Your codebase should read like the business it serves, not just at the class
level, but at the folder level too. When a newcomer opens your project, the
directory tree should name the parts of the business, so a newcomer can find
the code for a feature by knowing what the feature is called.

### In Classes

Protean's domain elements (aggregates, entities, value objects, commands,
events) map directly to DDD tactical patterns, so business requirements
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
`infrastructure/`, and completely destroy domain visibility. To understand a
single feature, you fish through three separate subtrees. Protean's decorators
(`@Aggregate`, `@CommandHandler`, `@Projection`, `@Repository`) already declare
what layer each element belongs to. The framework carries this architectural
metadata so your folder structure doesn't have to repeat it.

This means you organize by **domain concept**: aggregates as top-level folders,
capability files that colocate related commands and handlers, projections
grouped by the business question they answer. Every folder and file should be
something you'd explain to a product manager.

See the [Organize by Domain Concept](../../patterns/organize-by-domain-concept.md)
pattern for detailed structural guidance and examples.

## Prototype Rapidly, Iterate Freely

The first iteration of a model is rarely right. Effective models emerge
from exploring a problem from multiple angles and iterating on initial
ideas.

Protean ships **in-memory adapters** for databases, brokers, caches, and event
stores, so you can build and test the whole domain model without installing or
configuring anything. That leaves you free to concentrate on the model itself,
to throw away the first version and the second, and to arrive at a design by
refining it.

The loop is short: write an aggregate, test it against a business scenario,
adjust, repeat. There are no migrations to run and no broker to start.

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

When the framework's defaults don't fit, Protean provides **escape hatches**.
You can override its implementation and specify your own database models,
custom repository queries, or adapter-specific optimizations. The goal is
always to serve the domain, not to enforce architectural dogma.

## Evolve Architecture Incrementally

You don't need to decide your final architecture on day one. In early
stages of development, it's rare to clearly understand all the domains
and their boundaries. Premature decisions about these boundaries can
be detrimental as the project matures.

Protean is designed for **progressive evolution**:

- **Start with DDD**: application services, repositories, and events. This is
  the simplest way to build with Protean.
- **Add CQRS when you need it**: introduce commands, command handlers, and
  projections for specific aggregates.
- **Adopt Event Sourcing where it matters**: for aggregates that need full
  audit trails, temporal queries, or complex state transitions.

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
aggregates and bounded contexts. Events represent facts (things that happened)
and are propagated across the system to keep components in sync without direct
dependencies.

This event-centric approach enables:

- **Loose coupling** between bounded contexts that evolve independently
- **State synchronization** without shared databases or direct API calls
- **Event Sourcing** where aggregate state is derived entirely from
  events, with `@apply` handlers as the single source of truth for state mutations
  during both live operations and replay
- **Async processing** via the Protean server engine for production
  workloads

## Test with Confidence

Keeping the domain separate from infrastructure is what makes it testable.
Your domain model runs against in-memory adapters by default, so every
business rule can be covered without starting a single service.

The testing strategy works in layers:

- **Domain model tests** run entirely in-memory: fast, deterministic, and
  focused on business rules
- **Application tests** verify command handling, event processing, and
  service coordination
- **Integration tests** run against real databases and brokers when you
  need to verify adapter behavior

Protean supports `pytest` and `pytest-bdd` directly. Tests you write while
prototyping still pass once production infrastructure is plugged in, because
the domain logic they exercise has not changed.

---

## What belongs in Protean

Protean is opinionated. It guides you toward the DDD patterns it is built
around instead of accommodating every possible feature, and the same filter
decides what belongs in the framework itself:

- **Domain concerns belong in the framework; infrastructure concerns belong in
  adapters.** Schema migrations, document-style persistence, and storage-specific
  optimizations are adapter responsibilities. Protean defines the port contracts,
  and each adapter owns its own infrastructure.
- **DDD purity over convenience**: Aggregates have a single surrogate identity
  rather than composite keys. Validation lives in the domain layer as invariants,
  not in the database. Hard deletion is an infrastructure escape hatch, not a
  domain operation.
- **No abstractions over technology-specific concerns**: If a feature only makes
  sense for one adapter (Alembic migrations for SQLAlchemy, say), it does not
  belong in core Protean. The Ports and Adapters pattern exists precisely to keep
  those concerns separate.
- **Coherence over feature breadth**: Fixing inconsistencies, unifying patterns,
  and improving type safety come before adding new capabilities. A smaller,
  coherent framework serves you better than a large, sprawling one.

These are the boundaries a change is measured against, which is why a new feature
often begins as a conversation about whether it belongs in the framework at all.

---

## Further reading

- [The Always-Valid Domain](always-valid.md): How four validation layers
  guarantee that domain objects are never invalid.
