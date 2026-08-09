# Applicability charter

This page helps you decide whether Protean fits what you are building. It is as
clear about the systems Protean is not for as about the ones it is.

You can check most of it in an afternoon. Protean runs entirely in memory, with
no database, message broker, or other services to install, so you can build a
real slice of your system, see how it feels, and throw it away if it does not
fit. The [installation guide](../guides/getting-started/installation.md) and
[Hello, Protean!](../guides/getting-started/hello.md) get you to a running
example in a few minutes.

Protean is Apache-2.0 licensed and pre-1.0. What the pre-1.0 status means for an
upgrade is covered under [Before you commit](#before-you-commit). The short
version is that its public surface changes only under a written contract.

---

## In one sentence

**Protean is for backend systems in Python where the hard part is the business
rules, not moving large volumes of data at very low latency.**

If the difficulty in your system is the rules ("an order cannot ship before it is
paid", "a subscription in trial cannot be charged"), Protean is built to help. If
the difficulty is raw speed, or moving and crunching enormous amounts of data, it
is not.

Often these are **ambitious systems**: ones whose shape you cannot fully see on
day one, that have to grow safely over years instead of being rebuilt each time
they outgrow their last design. Protean is built for that kind of system in
particular, and the rest of this page says why, and where it stops.

---

## What Protean is built for

An "aggregate" below means one object and the data it owns, treated as a single
unit. That is the main term you need for this page.

**Systems whose hard part is the business rules**, and the states things move
through. Protean keeps those rules in one place and checks them on every change,
so an object cannot pass through the domain layer in an invalid state.

**New products whose final shape you cannot see yet**: a startup, a brand-new
build, a proof of concept meant to become the real thing. You do not have to fix
the model, the boundaries, or the technology up front. Start in memory with the
simplest approach, let the design emerge, and add richer patterns and real
infrastructure as they prove necessary. The model and its tests carry across
those changes, so the prototype grows into the product instead of being
rewritten.

**Systems that start simple and get more demanding over time.** Start plain, then
adopt separate read and write models, or a full event history, for the one part
of the system that needs them, without disturbing the rest.

**Systems where separate parts of the business must stay in step** by reacting to
things that happened. Within one deployment, one part can react to another's
events instead of calling it directly or sharing its database, so the parts stay
loosely coupled.

**Parts of the system that need a complete history**, such as an audit trail or
"what did this look like last month". Record those parts as a stream of events
and their state can be rebuilt from that history. You opt in where it is worth
the cost.

**Python backends on 3.11 or newer.** Protean is a Python framework, and your
model is ordinary, typed Python.

**A system you deploy and run yourself** that may later split into services. It
fits a single application you can grow and later divide, and its promises are
stated for stores you run, not a managed global service.

The databases it ships adapters for are specific ones: PostgreSQL, SQLite,
Microsoft SQL Server, and Elasticsearch. Redis backs the broker and cache, and
MessageDB backs the event store. There are in-memory versions of all of them for
development and tests. See [Adapters](adapters/index.md) for the details.

---

## What Protean is not built for

If your system is one of these, reach for a different tool. The sooner you see
the mismatch, the cheaper it is to act on.

| Shape of system | Why it is a poor fit | Consider instead |
|---|---|---|
| **Simple create/read/update/delete apps with little logic** | The parts that protect complex rules are pure overhead when there are no complex rules to protect. | A standard web framework or a plain database toolkit. |
| **Systems whose main challenge is speed or data volume** (ad bidding, high-frequency trading, packet processing) | Protean checks every change and processes work one object at a time on the Python runtime. That favours correctness over the lowest possible latency. | A purpose-built low-latency service, often written in another language. |
| **Analytics, reporting, or data-processing pipelines** | Protean handles transactions one business action at a time. It is not an engine for computing over huge datasets in batches or streams. | A stream processor or a data warehouse. |
| **Systems modeled around database tables first** | In Protean the rules live in the code, and each object has one simple identity. Uniqueness is the exception: you can declare unique fields and unique or partial indexes, and the database enforces them. If the table schema is your real model, you will be working against the framework. | A database toolkit or ORM with a schema-and-migrations workflow. |
| **Adding Protean on top of an existing app** by wrapping its current database models | Protean manages persistence for the objects it owns, through its own layer. It does not adopt or wrap the models an existing app already has. | Introduce Protean for a new, separate part of the system instead of retrofitting it onto current models. |
| **Real-time collaborative editing** where concurrent edits are merged automatically | When two changes collide, Protean detects the conflict and rejects one. It does not merge them. | A library built for automatic conflict resolution. |
| **Active-active across regions with strong consistency everywhere** | Its promises are stated for a single deployment against stores you run, not for one global, always-consistent system. | A globally distributed database with its own consistency model. |
| **Anything that is not a Python backend**: other languages, or the frontend and UI | Protean is a backend Python framework. It can expose your system over HTTP through [FastAPI](../guides/fastapi/index.md), but it is not a user-interface toolkit or a multi-language runtime. | The native framework for that language or layer. |
| **One-off scripts and short-lived jobs** | The upfront structure pays off across a long-lived system, and is pure cost for something you run once. | A plain script. Reach for Protean when the system has to last. |

---

## What you keep control of

The cost of a framework that turns out to be wrong is not the first week. It is
the years afterwards spent unable to move off it. So here is what Protean does
and does not take over.

- **Your model is plain Python that you own**: There are no framework base classes
  to inherit and no generated code you cannot read. A newcomer can read a class
  and understand what it does.
- **Infrastructure is configuration**: Which database, broker, or cache you use is
  a setting. Swapping one for another, or in-memory for a real one, does not touch
  your business logic.
- **There are escape hatches**: When the defaults do not fit, you can supply your
  own database models, write raw queries, or use a specific database's features
  directly.
- **You can test the whole model in memory**, with no services running, which keeps
  the feedback loop fast. See [Test your application](../guides/testing/index.md).
- **Leaving is bounded**: If you build on Protean and later move off, the business
  logic is the part you keep, as plain Python. What you would replace is the
  wiring around it: persistence, and the event and handler plumbing.

Protean also states its promises in writing and tests against them. See the
[guarantees](guarantees.md) for what it holds per store, and the
[versioning policy](versioning-policy.md) for what an upgrade can and cannot do
to your code.

---

## Scale and how you run it

Most business systems fall between the two extremes this page rules out.
Ordinary web, API, and line-of-business backends, and SaaS products, are well
within what Protean is built to handle. The two ends, the lowest-latency work
and the highest-volume data processing, fall outside its design.

Protean is built for systems that grow in complexity, and its scaling model
follows from that.

- **The unit of consistency is one object and the data it owns**: You scale by
  keeping those small and splitting the data across many of them, rather than by
  locking large graphs of objects in one transaction.
- **Background work scales across many workers**: Processing that runs in the
  background can be spread across workers to keep up with load.
- **One kind of background reader runs as a single writer by design**: An
  event-store subscription is not meant to be cloned across workers, and Protean
  refuses to start more than one of it by default, on a best-effort basis. When
  you need that kind of work to scale out, use a stream subscription, which is
  built for it. See
  [Subscriptions & delivery](guarantees.md#subscriptions-delivery).
- **Background processing needs an always-on worker**: The background engine and
  its retry and delivery machinery assume a process that keeps running, so that
  side of Protean does not fit a scale-to-zero or serverless-function model.
  Handling work synchronously, inside a normal request, has no such requirement.

A few things are deliberately out of scope, and the
[guarantees reference](guarantees.md#out-of-scope) lists them, including delivery
of events to separately-deployed parts of the system, which is not yet a firm
promise, and nesting one transaction inside another.

For the exact promises on ordering, delivery, consistency, and isolation per
store, read the [guarantees reference](guarantees.md). That is the precise
contract; this page tells you whether your system is one it applies to.

---

## Before you commit

Work through these:

- **Where is the hard part of your system?** Business rules put you in scope.
  Speed or data volume put you out of it.
- **Would you describe your system as objects with rules, and things that happen
  to them over time?** If that description does not fit, the framework will not
  either.
- **Do the shipped [adapters](adapters/index.md) cover your datastore?** A store
  that is not on the list, with no one to write an adapter for it, is a real cost.
- **Do the [guarantees](guarantees.md) cover what your system relies on?** If you
  need something they place out of scope, plan for it or pick another tool.
- **Is your team ready to learn the modeling approach?** Protean is built around
  Domain-Driven Design. Those are standard, widely documented patterns, so the
  skills transfer, but expect a learning curve if they are new to your team.
- **Is a pre-1.0 framework acceptable for your commitment?** Protean's public
  surface changes only under a written
  [compatibility contract](versioning-policy.md), and a few promises are still
  marked interim. Weigh that against how long-lived your system needs to be.

For the thinking behind these boundaries, see the
[philosophy](../concepts/philosophy/index.md), which applies the same test to
Protean itself.

---

## Related reading

- [Hello, Protean!](../guides/getting-started/hello.md): Build and run a real slice in a few minutes.
- [Consistency & delivery guarantees](guarantees.md): The exact promises per store.
- [Versioning policy](versioning-policy.md): What a version number promises, so you can plan upgrades.
- [Stable surface](stable-surface.md): Which parts of Protean the compatibility contract covers.
- [Philosophy & design principles](../concepts/philosophy/index.md): The thinking behind the boundaries above.
- [Choose a path](../guides/pathways/index.md): The simplest approach to start with, and how to grow from it.
