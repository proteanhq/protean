# Why Protean?

You work out the model on a whiteboard: aggregates, events, bounded contexts.
Then you open your editor and the code stops matching the drawing. The ORM wants
tables, so the aggregate becomes rows. Validation is something you remember to
call. Infrastructure details work their way into the business logic. A few months
later the drawing and the code describe different systems.

Protean starts somewhere else: **your domain model is the architecture.** You
write it in Python as you drew it, and the framework takes care of the rest.

Four capabilities make that work.

---

## 1. The domain compiler

Most frameworks treat your domain classes as configuration for database tables or
API schemas. Protean treats them as a **complete, inspectable specification** of
your system.

When you define aggregates, entities, value objects, commands, events, and
handlers, Protean builds an Intermediate Representation (IR): a portable JSON
structure that captures your whole domain topology, including element types,
relationships, field schemas, event flows, handler wiring, and cluster
boundaries.

```python
domain = Domain()

# Define your domain elements...

domain.init()
ir = domain.to_ir()
```

The IR is what everything else builds on: architecture documentation, API spec
generation, contract testing, schema registries, and visual domain exploration.
Your domain model is not only runtime code. It is a machine-readable
specification that tools can analyze, compare, and generate from.

**What this means for you.** Define your domain once in Python. Derive
documentation, API specs, and contracts from it. Detect breaking changes before
they ship.

[:material-arrow-right-box: IR Specification](./concepts/internals/ir-specification.md)

---

## 2. The always-valid domain

In most frameworks, validation is something you opt into. You call `validate()`,
`clean()`, or `is_valid()`, and between those calls your objects can hold any
state at all. Miss a check and invalid data spreads quietly.

Protean checks validity continuously. **Domain objects are always valid, or they
don't exist.** Every field assignment triggers validation of field constraints,
value object invariants, and aggregate business rules, on every change, rolled
back on failure.

```python
@domain.aggregate
class Order:
    customer_id: Identifier(required=True)
    status: String(max_length=20, default="draft")
    items = HasMany("OrderItem")

    @invariant.post
    def must_have_items_when_placed(self):
        if self.status != "draft" and not self.items:
            raise ValidationError(
                {"items": ["Order must have at least one item"]}
            )

# Rejected immediately, so no invalid state is possible
order = Order(customer_id="cust-1", status="confirmed")
# → ValidationError: Order must have at least one item
```

Four layers of validation work together:

| Layer | What it catches | Where it is declared |
|-------|----------------|----------------|
| Field constraints | Types, ranges, required-ness | Field declarations |
| Value object invariants | Format rules, concept-level validity | Value objects |
| Aggregate invariants | Business rules, cross-field consistency | Aggregates |
| Handler guards | Authorization, context, cross-aggregate rules | Handlers and services |

You write no `validate()` calls, and there is no window between method calls in
which an object can be invalid. The aggregate refuses changes that violate its
rules.

[:material-arrow-right-box: The Always-Valid Domain](./concepts/philosophy/always-valid.md)

---

## 3. Progressive architecture

Ambitious systems rarely arrive fully formed, and you do not need to decide your
final architecture on day one. Protean supports three approaches that build on
each other, so you can start simple and add sophistication where and when you
need it. An early prototype grows into the product instead of being rewritten.

**Start with domain-driven design.** Aggregates, application services,
repositories. This is the simplest way to build with Protean: no commands, no
event handlers, no projections, just a clean domain model with persistence.

```python
@domain.application_service(part_of=Post)
class PostService:
    @use_case
    def create_post(self, title: str, body: str) -> str:
        post = Post(title=title, body=body)
        current_domain.repository_for(Post).add(post)
        return post.id
```

**Add CQRS when you need it.** When one aggregate needs separate read and write
models, introduce commands, command handlers, and projections for that aggregate
alone. The others stay as they are.

```python
@domain.command(part_of=Post)
class PublishPost:
    post_id: Identifier(required=True)

@domain.command_handler(part_of=Post)
class PostCommandHandler:
    @handle(PublishPost)
    def publish(self, command: PublishPost):
        repo = current_domain.repository_for(Post)
        post = repo.get(command.post_id)
        post.publish()
        repo.add(post)
```

**Adopt event sourcing where it matters.** For aggregates that need a full audit
trail, temporal queries, or complex state reconstruction, switch to event
sourcing without rewriting the rest of your system.

```python
@domain.aggregate(event_sourced=True)
class Account:
    balance: Float(default=0.0)

    @apply
    def deposited(self, event: Deposited):
        self.balance += event.amount
```

You can mix these. One aggregate uses domain-driven design, another uses CQRS, a
third uses event sourcing, all in the same domain, the same codebase, and the
same test suite.

[:material-arrow-right-box: Choose a Path](./guides/pathways/index.md)

---

## 4. Infrastructure portability

Your domain model should know nothing about databases, message brokers, or
caches. In Protean, infrastructure is **configuration**.

Start with no setup at all:

```python
domain = Domain()
# In-memory database, in-memory broker, in-memory cache
# No Docker, no services, no configuration files
```

When you are ready for production, change `domain.toml`:

```toml
[databases.default]
provider = "postgresql"
database_uri = "${DATABASE_URL}"

[brokers.default]
provider = "redis"
URI = "${REDIS_URL}"

[event_store]
provider = "message_db"
database_uri = "${MESSAGE_DB_URL}"
```

Your domain logic, tests, and business rules stay untouched. The framework
handles the wiring.

| Port | Available adapters |
|------|-------------------|
| Database | Memory, PostgreSQL, SQLite, MSSQL, Elasticsearch |
| Broker | Inline, Redis Streams, Redis PubSub |
| Event Store | Memory, MessageDB |
| Cache | Memory, Redis |

The payoff goes beyond convenience. Your domain model tests run in memory in
milliseconds, your CI pipeline needs no Docker services for core logic tests, and
moving one aggregate from PostgreSQL to Elasticsearch is a configuration change.

[:material-arrow-right-box: Adapters](./reference/adapters/index.md)

---

## Built to last

The engineering behind these capabilities:

- A large test suite (**12,000+ tests**, about three lines of test per line of
  code). See [Quality](community/quality.md) for the current breakdown.
- Every commit tested against PostgreSQL, Redis, Elasticsearch, MessageDB,
  MSSQL, and SQLite, on **Python 3.11 through 3.14**.
- Zero lint violations, A-grade maintainability, and an average cyclomatic
  complexity of 3.38.
- [CloudEvents v1.0](https://cloudevents.io/) compliant event serialization, for
  interoperability with other systems.

[:material-arrow-right-box: Quality Report](./community/quality.md)

---

## Get started

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

</div>
