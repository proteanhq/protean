# Why Protean?

You've stood at the whiteboard. Aggregates, events, bounded contexts -- the
model is clear. Then you open your editor and the framework fights you.
ORMs want tables, not aggregates. Validation is opt-in. Infrastructure
bleeds into domain logic. The whiteboard rots.

Protean starts from a different place: **your domain model is the
architecture.** Write it in Python exactly as you drew it. The framework
handles the rest.

These four capabilities make that possible.

---

## 1. The domain compiler

Most frameworks treat your domain classes as configuration for database tables
or API schemas. Protean treats them as a **complete, inspectable specification**
of your system.

When you define aggregates, entities, value objects, commands, events, and
handlers, Protean builds an Intermediate Representation (IR) -- a portable
JSON structure that captures your entire domain topology: element types,
relationships, field schemas, event flows, handler wiring, and cluster
boundaries.

```python
domain = Domain()

# Define your domain elements...

domain.init()
ir = domain.to_ir()
```

The IR is the foundation for everything that follows: architecture
documentation, API spec generation, contract testing, schema registries,
and visual domain exploration. Your domain model isn't just runtime code --
it's a machine-readable specification that tools can analyze, compare, and
generate from.

**What this means:** Define your domain once in Python. Derive documentation,
API specs, and contracts automatically. Detect breaking changes before they
ship.

[:material-arrow-right-box: IR Specification](./concepts/internals/ir-specification.md)

---

## 2. The always-valid domain

In most frameworks, validation is opt-in. You call `validate()`, `clean()`,
or `is_valid()` -- and between those calls, your objects can exist in any
state. Forget a check, and invalid data propagates silently.

Protean enforces validity continuously. **Domain objects are always valid, or
they don't exist.** Every field assignment triggers automatic validation:
field constraints, value object invariants, and aggregate business rules --
checked on every change, rolled back on failure.

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

# This is rejected immediately -- no invalid state possible
order = Order(customer_id="cust-1", status="confirmed")
# → ValidationError: Order must have at least one item
```

Four validation layers work together:

| Layer | What it catches | Where it lives |
|-------|----------------|----------------|
| Field constraints | Types, ranges, required-ness | Field declarations |
| Value object invariants | Format rules, concept-level validity | Value objects |
| Aggregate invariants | Business rules, cross-field consistency | Aggregates |
| Handler guards | Authorization, context, cross-aggregate rules | Handlers/services |

No `validate()` calls. No forgotten checks. No invalid state between method
calls. The aggregate simply refuses to accept changes that violate its rules.

[:material-arrow-right-box: The Always-Valid Domain](./concepts/philosophy/always-valid.md)

---

## 3. Progressive architecture

You don't need to decide your final architecture on day one. Protean supports
three approaches that build on each other -- start simple, add sophistication
only where and when you need it.

**Start with DDD.** Aggregates, application services, repositories. The
simplest way to build with Protean -- no commands, no event handlers, no
projections. Just a clean domain model with persistence.

```python
@domain.application_service(part_of=Post)
class PostService:
    @use_case
    def create_post(self, title: str, body: str) -> str:
        post = Post(title=title, body=body)
        current_domain.repository_for(Post).add(post)
        return post.id
```

**Add CQRS when you need it.** When one aggregate needs separate read and
write models, introduce commands, command handlers, and projections -- for
that aggregate only. Other aggregates stay simple.

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

**Adopt Event Sourcing where it matters.** For aggregates that need full
audit trails, temporal queries, or complex state reconstruction, switch to
event sourcing -- without rewriting the rest of your system.

```python
@domain.aggregate(is_event_sourced=True)
class Account:
    balance: Float(default=0.0)

    @apply
    def deposited(self, event: Deposited):
        self.balance += event.amount
```

Mix patterns freely. One aggregate uses DDD, another uses CQRS, a third uses
Event Sourcing -- all in the same domain, the same codebase, the same test
suite.

[:material-arrow-right-box: Choose a Path](./guides/pathways/index.md)

---

## 4. Infrastructure portability

Your domain model should know nothing about databases, message brokers, or
caches. In Protean, infrastructure is defined through **configuration, not
code**.

Start with zero setup:

```python
domain = Domain()
# In-memory database, in-memory broker, in-memory cache
# No Docker, no services, no configuration files
```

When you're ready for production, swap via `domain.toml`:

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

Your domain logic, tests, and business rules remain untouched. The framework
handles the wiring.

| Port | Available Adapters |
|------|-------------------|
| Database | Memory, PostgreSQL, SQLite, Elasticsearch |
| Broker | Inline, Redis Streams, Redis PubSub |
| Event Store | Memory, MessageDB |
| Cache | Memory, Redis |

This isn't just about convenience. It means your domain model tests run
in-memory in milliseconds, your CI pipeline doesn't need Docker services for
core logic tests, and switching from PostgreSQL to Elasticsearch for a
specific aggregate is a configuration change.

[:material-arrow-right-box: Adapters](./reference/adapters/index.md)

---

## Built to last

Protean backs these capabilities with engineering rigor:

- **3,826 tests** with a 3.5:1 test-to-code ratio
- Every commit tested against PostgreSQL, Redis, Elasticsearch, MessageDB,
  MSSQL, and SQLite across **Python 3.11--3.14**
- Zero lint violations, A-grade maintainability, average cyclomatic
  complexity of 2.97
- [CloudEvents v1.0](https://cloudevents.io/) compliant event serialization
  for cross-system interoperability

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

    10-chapter tutorial from your first aggregate to production.

    [:material-arrow-right-box: Tutorial](./guides/getting-started/tutorial/index.md)

</div>
