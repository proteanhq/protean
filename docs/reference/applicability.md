# Applicability charter

This page states plainly what Protean is a good fit for, and the shapes of
systems it is **not** a good fit for, with the reason in each case. Read it
before you invest, so you can decide whether the framework matches the system
you are building.

An honest "when not to use this" saves you from a bad fit and spares the project
from being stretched into shapes it was never designed for. Falling outside the
scope below is not a failure on your part or a bug in Protean. It is a signal to
reach for a different tool, and the sooner you see the mismatch the cheaper it
is to act on.

---

## In one sentence

**Protean is for domain-rich, transactional backend systems in Python whose hard
part is the business model, not raw throughput or data volume.**

If the difficulty in your system lives in the rules ("an order cannot ship
before it is paid", "a subscription in trial cannot be dunned"), Protean is built
to help. If the difficulty lives in moving a firehose of data with the lowest
possible latency, or in crunching analytics over billions of rows, it is not.

---

## What Protean is built for

| Shape of system | Why it fits |
|---|---|
| **Domain-rich backend services** where the complexity is in business rules and invariants | Aggregates, invariants, and the always-valid model exist precisely to keep those rules correct and in one place. |
| **Systems you would sketch as aggregates, events, and bounded contexts** | Those DDD concepts are the framework's native building blocks; you write the model as you drew it, not translated into tables. |
| **Systems that grow in sophistication over time** | Start with plain DDD, add CQRS for one aggregate, adopt Event Sourcing where it earns its keep, all in one codebase. See [Choose a path](../guides/pathways/index.md). |
| **Event-driven integration between bounded contexts in one deployment** | Within a deployment, events keep contexts in sync without shared databases or direct calls. Delivery of `published` events to separately-deployed contexts is a different case; see [Scale and deployment shape](#scale-and-deployment-shape). |
| **Specific aggregates that need a full audit trail or temporal queries** | Model those aggregates as event-sourced and their state reconstructs from the event stream. It is opt-in per aggregate, not automatic for every one. |
| **Python backends on 3.11 or newer** | Protean is a Python framework; the domain model is ordinary typed Python. |
| **Modular monoliths and a small set of services you deploy and operate yourself** | The bounded-context model and the single-deployment server fit a monolith you can later split; the guarantees are stated for stores you run, not a managed global fabric. |

The infrastructure it supports (relational and document databases, Redis, an
event store, and in-memory equivalents for prototyping and tests) is listed in
[Adapters](adapters/index.md). The in-memory adapters are for development and
tests, not production.

---

## What Protean is not built for

| Shape of system | Why it is a poor fit | Consider instead |
|---|---|---|
| **CRUD applications with little domain logic** | Aggregates, invariants, commands, and events are overhead you pay for and never use; the model earns its keep only when there are rules to protect. | A CRUD-oriented web framework or a plain ORM. |
| **Ultra-low-latency or high-throughput data-plane hot paths** (ad bidding, high-frequency trading, packet processing) | Every field assignment runs validation, events dispatch through the engine, and persistence is aggregate-at-a-time on the Python runtime. That is correctness-first, not microsecond-first. | A purpose-built low-latency service, often outside Python. |
| **Big-data, analytics, or stream-processing pipelines** | Protean is a transactional domain framework, not a data-processing engine. It transacts at the aggregate boundary; it does not do batch or streaming computation over massive datasets. | A stream processor (Flink, Kafka Streams) or a data warehouse. |
| **Table-first or migrations-first modeling** | Validation lives in the domain as invariants, not as declarative database CHECK or exclusion constraints, and an aggregate has a single surrogate identity (no composite keys). Uniqueness is the exception: `unique=` fields and unique or partial indexes are declared and enforced in the database. If the relational schema is your model, the rest will fight you. | An ORM or query builder with a schema-migration workflow. |
| **Bolting onto an existing ORM-centric application** by wrapping its models | Protean owns persistence for the aggregates it manages, through its own adapters; it does not adopt or wrap your existing ORM models. | Introduce Protean for a new bounded context beside the existing app, rather than retrofitting it onto current models. |
| **Real-time collaborative editing with automatic merge** | Concurrency control is optimistic at the aggregate root: a conflicting write is detected and rejected, not merged. | A CRDT library or an operational-transform engine. |
| **Multi-region active-active with strong cross-region consistency** | The concurrency and delivery guarantees are stated for a single deployment against stores you run; global strong consistency is not part of the model. | A globally distributed database with its own consistency model. |
| **Non-Python stacks, or frontend and UI work** | Protean is a backend Python framework. It exposes the domain over HTTP through FastAPI, but it is not a UI toolkit or a polyglot runtime. | The native framework for that language or layer. |
| **Throwaway scripts and one-off jobs** | The setup that pays off across a long-lived domain is pure cost for a script you run once. | A plain script; reach for Protean when the model has to last. |

---

## Scale and deployment shape

Protean is designed for domain complexity, not for raw scale, and its scaling
model follows from that.

- **The aggregate is the unit of consistency and concurrency.** Each aggregate
  is guarded by optimistic concurrency on its root ([ADR-0013](../adr/0013-optimistic-concurrency-and-claim-contract.md)).
  You scale by keeping aggregates small and well-partitioned, not by holding
  large graphs in one transaction.
- **Asynchronous work scales horizontally through stream subscriptions.** A
  handler fans out across workers using a stream subscription backed by Redis
  consumer groups.
- **A single event-store subscription is single-writer.** Protean refuses to run
  more than one worker for an event-store subscription unless you explicitly opt
  out, because those subscriptions have no cluster-wide ownership. Scale that
  kind of handler with a stream subscription, not by cloning the worker.
- **Asynchronous processing needs a long-lived worker.** The background engine,
  the periodic recovery pass, and the outbox processor all assume a persistent
  process, so the async path does not fit a scale-to-zero or function runtime.
  Synchronous, in-process processing carries no such requirement and runs fine in
  a request-scoped service.

A few things are deliberately outside this scope. The
[guarantees reference](guarantees.md#out-of-scope) lists them, including
delivery of `published` events to separately-deployed bounded contexts (not yet
a settled guarantee) and nested Units of Work (an inner unit reuses the outer
transaction rather than nesting).

For the exact per-port, per-adapter promises on ordering, delivery, consistency,
and isolation, read the [guarantees reference](guarantees.md). That is the
normative contract; this page tells you whether your system is one it applies to.

---

## Deciding, honestly

Work through these before you commit:

- **Where is the hard part of your system?** Business rules put you in scope;
  throughput, latency, or analytics volume put you out of it.
- **Would you naturally draw this as aggregates, events, and bounded contexts?**
  If not, the framework's shape will feel imposed rather than helpful.
- **Do the shipped [adapters](adapters/index.md) cover your infrastructure?** A
  datastore that is not in the list, with no one to write an adapter, is a real
  cost.
- **Do the [guarantees](guarantees.md) cover what your system relies on?** If you
  need something they mark out of scope, plan for it explicitly or pick a
  different tool.
- **Is your team comfortable with DDD?** The questions above assume fluency with
  aggregates, events, and bounded contexts. If those are new, budget for the
  learning curve; Protean guides you toward the patterns but expects them.
- **Is the framework mature enough for your commitment?** Protean is pre-1.0. Its
  public surface changes only under a deprecation-managed
  [compatibility contract](versioning-policy.md), and some guarantees are still
  marked interim. Weigh that before a long-lived bet.

Two pointers help you stay in scope once you have chosen Protean:

- The [philosophy](../concepts/philosophy/index.md) explains what belongs in the
  framework and what does not. It applies the same test to Protean that these
  questions apply to your system.
- [`protean check`](cli/check.md) and its [fitness functions](fitness-functions.md)
  flag specific patterns that hurt at scale or couple the domain to its
  infrastructure. They check habits inside a system Protean already fits; this
  page is the earlier question of whether it fits at all.

---

## Related reading

- [Consistency & delivery guarantees](guarantees.md): the exact per-port, per-adapter contract.
- [Versioning policy](versioning-policy.md): what a version number promises, so you can plan upgrades.
- [Stable surface](stable-surface.md): which names the compatibility contract covers.
- [Philosophy & design principles](../concepts/philosophy/index.md): the convictions behind the boundaries above.
- [Choose a path](../guides/pathways/index.md): DDD, CQRS, or Event Sourcing, and how to grow between them.
