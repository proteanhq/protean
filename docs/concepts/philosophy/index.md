# What principles guide Protean's design?

Protean starts from one idea: **your domain logic should decide your
architecture.** Protean follows Domain-Driven Design, stays pragmatic about
technology, and lets your application change as the business changes.

These are the principles behind the design decisions.

## Mirror the Domain in Code

Your code should use the names the business uses, in its folders as well as in
its classes. Your directory tree should name the parts of the business. A
newcomer to your project can then find the code for a feature from the
feature's name.

### Name business concepts in your classes

Protean's domain elements (aggregates, entities, value objects, commands,
events) map directly to DDD tactical patterns, so business requirements
translate naturally into code.

Python's readability is a deliberate advantage here. Domain experts and
developers can look at the same aggregate class and have a shared
conversation about what the system does. There is no ORM inheritance to
decipher, no framework-specific base classes to learn. A `Post` aggregate
with a `publish()` method reads exactly like what it is.

### Name business concepts in your folders

The same principle extends to how you organize files. **Your folders name the
"what" (domain concepts). The framework records the "which kind" (layer, side,
boundary).**

Classic layered approaches split code into `domain/`, `application/`,
`infrastructure/`. That split hides the domain concepts from anyone who reads
the folder tree. To understand a single feature, you have to search three
separate subtrees. Protean's decorators (`@Aggregate`, `@CommandHandler`,
`@Projection`, `@Repository`) already declare what layer each element belongs
to. The framework carries this architectural metadata so your folder structure
doesn't have to repeat it.

This means you organize by **domain concept**: aggregates as top-level folders,
capability files that colocate related commands and handlers, projections
grouped by the business question they answer. Every folder and file should be
something you'd explain to a product manager.

See the [Organize by Domain Concept](../../patterns/organize-by-domain-concept.md)
pattern for detailed structural guidance and examples.

## Prototype Rapidly, Iterate Freely

The first iteration of a model is rarely right. You reach an effective model by
exploring a problem from several angles and revising your first ideas.

Protean ships **in-memory adapters** for databases, brokers, caches, and event
stores, so you can build and test the whole domain model without installing or
configuring anything. You can then concentrate on the model itself. You can
throw away the first version and the second, and reach a design by refining it.

The loop is short: write an aggregate, test it against a business scenario,
adjust, repeat. There are no migrations to run and no broker to start.

## Separate Domain from Infrastructure

Developers often put technology concerns into business logic without meaning
to. Over time, your domain code depends on a specific database and your
business rules contain API serialization code. Changing any technology then
means rewriting core logic.

Protean enforces a clean separation through the **Ports and Adapters**
(Hexagonal) architecture. Your domain model contains no code for databases,
message brokers, or caches. Infrastructure is defined through configuration,
not code changes:

- **Databases**: PostgreSQL, Elasticsearch, or in-memory
- **Brokers**: Redis Streams, Redis Pub/Sub, or inline (synchronous)
- **Event Stores**: MessageDB or in-memory
- **Caches**: Redis or in-memory

Switching from an in-memory store to PostgreSQL is a configuration change. Your
domain logic, tests, and business rules remain untouched. Protean initializes
and injects infrastructure elements at runtime. Your core logic therefore stays
the same across local development, CI/CD, and production.

## Choose the pattern that fits each aggregate

Real-world applications rarely fit a single architectural pattern perfectly. If
you force CQRS on every component, you over-engineer some components and
under-serve others. Protean takes a **pragmatic approach**: you can mix
architectural patterns at the aggregate level within the same domain.

One aggregate might use simple DDD with application services. Another
might need CQRS with commands and projections. A third might require
full Event Sourcing for audit trails. Protean supports all three in the
same codebase, provided the decisions are explicit and well-documented.

When the framework's defaults don't fit, Protean provides **escape hatches**:
places where you replace a default with your own code. You can override its
implementation and specify your own database models, custom repository queries,
or adapter-specific optimizations. Protean always puts the needs of the domain
ahead of any fixed architectural rule.

## Evolve Architecture Incrementally

You don't need to decide your final architecture when you start the project. In
early stages of development, it's rare to clearly understand all the domains
and their boundaries. If you decide these boundaries too early, those decisions
can hurt the project as it matures.

Protean is designed for **progressive evolution**:

- **Start with DDD**: application services, repositories, and events. This is
  the simplest way to build with Protean.
- **Add CQRS when you need it**: introduce commands, command handlers, and
  projections for specific aggregates.
- **Adopt Event Sourcing where it matters**: for aggregates that need full
  audit trails, temporal queries, or complex state transitions.

As your understanding deepens, you can decompose a monolithic domain into
finer-grained **bounded contexts**, extract subdomains, and evolve your
architecture without rewriting from scratch. Because you can test the whole
domain model in Protean, your tests catch regressions while you do this
refactoring.

Technology decisions follow the same principle: **defer until the last
responsible moment.** Start with in-memory adapters, prove your domain
model works, then choose your production stack. Even after choosing,
Protean's configuration-based approach makes switching costs extremely
low.

## Communicate Through Events

As systems grow, tight coupling between subdomains creates fragility. A change
in one bounded context forces changes in other bounded contexts, and the whole
system becomes harder to maintain.

Protean uses **events as the primary communication mechanism** between
aggregates and bounded contexts. Events record facts (things that happened).
Protean propagates events across the system, so components stay in sync without
direct dependencies.

This event-centric approach enables:

- **Loose coupling** between bounded contexts that evolve independently
- **State synchronization** without shared databases or direct API calls
- **Event Sourcing**, where Protean derives aggregate state entirely from
  events. `@apply` handlers are the single source of truth for state mutations
  during both live operations and replay
- **Async processing** via the Protean server engine for production
  workloads

## Test with Confidence

Because you keep the domain separate from infrastructure, you can test the
domain on its own. Your domain model runs against in-memory adapters by
default, so every business rule can be covered without starting a single
service.

The testing strategy works in layers:

- **Domain model tests** run entirely in-memory: fast, deterministic, and
  focused on business rules
- **Application tests** verify command handling, event processing, and
  service coordination
- **Integration tests** run against real databases and brokers when you
  need to verify adapter behavior

Protean supports `pytest` and `pytest-bdd` directly. Your prototyping tests
still pass after you connect production infrastructure. The domain logic those
tests exercise has not changed.

---

## What belongs in Protean

Protean is opinionated. Protean guides you toward the DDD patterns it is built
around and does not try to support every possible feature. The Protean
maintainers use the same test to decide what belongs in the framework itself:

- **Domain concerns belong in the framework; infrastructure concerns belong in
  adapters.** Schema migrations, document-style persistence, and storage-specific
  optimizations are adapter responsibilities. Protean defines the port contracts,
  and each adapter owns its own infrastructure.
- **Protean chooses DDD purity over convenience**: Aggregates have a single
  surrogate identity instead of composite keys. You write validation as
  invariants in the domain layer, and the database holds no validation rules.
  Protean offers hard deletion only as an infrastructure exception. The domain
  layer has no hard-delete operation.
- **Protean adds no abstractions over technology-specific concerns**: Protean
  wraps no technology in a generic layer of its own. When a feature makes sense
  only for some adapters, those adapters implement the feature with their
  technology's own tools and declare it as a capability. Protean uses the
  feature only with adapters that declare it.
- **Protean puts coherence before feature breadth**: Fixing inconsistencies,
  unifying patterns, and improving type safety come before adding new
  capabilities. A smaller, coherent framework serves you better than a large,
  sprawling one.

The Protean maintainers measure every proposed change against these boundaries.
A new feature therefore often starts with a discussion of whether it belongs in
the framework at all.

---

## Read more about Protean's principles

- [The Always-Valid Domain](always-valid.md): How Protean checks domain objects
  at four validation layers so that no domain object is ever invalid.
