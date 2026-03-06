# Decorators

!!! abstract "Applies to: DDD · CQRS · Event Sourcing"

Every domain element in Protean is registered with a decorator on the
`Domain` instance. The decorator configures the element, wires it into the
domain registry, and accepts **options** that control its runtime behavior.

Options are passed as keyword arguments:

```python
@domain.aggregate(schema_name="users", fact_events=True)
class User:
    name = String(required=True)
```

All options are accessible at runtime via `element.meta_`.

---

## Domain Model

### `Domain.aggregate`

The root entity of a consistency boundary. Aggregates encapsulate business
logic, enforce invariants, and own the transaction lifecycle.

| Option | Default | Description |
|--------|---------|-------------|
| `abstract` | `False` | Cannot be instantiated when `True` |
| `auto_add_id_field` | `True` | Auto-adds an `id` identity field |
| `is_event_sourced` | `False` | Enables event sourcing for this aggregate |
| `fact_events` | `False` | Auto-generates fact events on state changes |
| `provider` | `"default"` | Database provider name |
| `schema_name` | `snake_case(cls)` | Table or collection name |
| `stream_category` | `snake_case(cls)` | Message stream category |
| `database_model` | `None` | Custom database model class |
| `limit` | `100` | Default query result limit |

Guide: [Aggregates](../../guides/domain-definition/aggregates.md)

### `Domain.entity`

An object with identity that lives inside an aggregate. Entities are always
accessed through their parent aggregate and cannot exist independently.

| Option | Default | Description |
|--------|---------|-------------|
| **`part_of`** | — | **Required.** Parent aggregate class |
| `auto_add_id_field` | `True` | Auto-adds an `id` identity field |
| `provider` | `"default"` | Database provider name |
| `schema_name` | `snake_case(cls)` | Table or collection name |
| `database_model` | `None` | Custom database model class |
| `limit` | `100` | Default query result limit |

Guide: [Entities](../../guides/domain-definition/entities.md)

### `Domain.value_object`

An immutable object defined entirely by its attributes, with no identity.
Two instances with the same attributes are equal.

| Option | Default | Description |
|--------|---------|-------------|
| `abstract` | `False` | Cannot be instantiated when `True` |
| `part_of` | `None` | Owning aggregate or entity (optional) |

Guide: [Value Objects](../../guides/domain-definition/value-objects.md)

### `Domain.domain_service`

Stateless business logic that spans multiple aggregates. Domain services
encapsulate cross-aggregate rules and run invariants for validation.

| Option | Default | Description |
|--------|---------|-------------|
| **`part_of`** | — | **Required.** List of two or more associated aggregates |

Guide: [Domain Services](../../guides/domain-behavior/domain-services.md)

---

## Messages

### `Domain.command`

An immutable DTO representing an intent to change aggregate state. Named
with imperative verbs (`PlaceOrder`, `RegisterUser`).

| Option | Default | Description |
|--------|---------|-------------|
| `abstract` | `False` | Cannot be instantiated when `True` |
| **`part_of`** | — | **Required.** Target aggregate class |

Guide: [Commands](../../guides/change-state/commands.md)

### `Domain.event`

An immutable fact representing a state change that has occurred. Named in
past tense (`OrderPlaced`, `CustomerRegistered`).

| Option | Default | Description |
|--------|---------|-------------|
| `abstract` | `False` | Cannot be instantiated when `True` |
| **`part_of`** | — | **Required.** Aggregate that raises this event |

Events also support a `__version__` class attribute (default `1`) for
schema versioning.

Guide: [Events](../../guides/domain-definition/events.md)

### `Domain.query`

An immutable read intent targeting a projection — the read-side counterpart
of commands.

| Option | Default | Description |
|--------|---------|-------------|
| `abstract` | `False` | Cannot be instantiated when `True` |
| **`part_of`** | — | **Required.** Associated projection class |

Guide: [Projections — Query](../../guides/consume-state/projections.md#querying-projections)

---

## Handlers

### `Domain.command_handler`

Receives commands and orchestrates aggregate state changes. Uses
`@handle(CommandClass)` to route commands to handler methods.

| Option | Default | Description |
|--------|---------|-------------|
| **`part_of`** | — | **Required.** Target aggregate class |
| `stream_category` | from aggregate | Message stream category |
| `subscription_type` | `None` | Subscription behavior enum |
| `subscription_profile` | `None` | Subscription profile enum |
| `subscription_config` | `{}` | Custom subscription configuration |

Guide: [Command Handlers](../../guides/change-state/command-handlers.md)

### `Domain.event_handler`

Reacts to domain events and orchestrates side effects. Uses
`@handle(EventClass)` to route events to handler methods.

| Option | Default | Description |
|--------|---------|-------------|
| **`part_of`** | — | **Required.** Source aggregate class |
| `source_stream` | `None` | Custom event stream source |
| `stream_category` | from aggregate | Message stream category |
| `subscription_type` | `None` | Subscription behavior enum |
| `subscription_profile` | `None` | Subscription profile enum |
| `subscription_config` | `{}` | Custom subscription configuration |

Guide: [Event Handlers](../../guides/consume-state/event-handlers.md)

### `Domain.query_handler`

Processes queries and returns results from projections. Uses
`@read(QueryClass)` to route queries to handler methods. Unlike `@handle`,
`@read` does not wrap execution in a Unit of Work.

| Option | Default | Description |
|--------|---------|-------------|
| **`part_of`** | — | **Required.** Associated projection class |

Guide: [Query Handlers](../../guides/consume-state/query-handlers.md)

### `Domain.application_service`

Orchestrates use cases by coordinating aggregates, repositories, and domain
services. Uses `@use_case` for automatic Unit of Work wrapping.

| Option | Default | Description |
|--------|---------|-------------|
| **`part_of`** | — | **Required.** Associated aggregate class |

Guide: [Application Services](../../guides/change-state/application-services.md)

---

## Read Models

### `Domain.projection`

A denormalized, query-optimized read model used on the read side of CQRS.
Projections support only simple field types — no associations or value
objects.

| Option | Default | Description |
|--------|---------|-------------|
| `abstract` | `False` | Cannot be instantiated when `True` |
| `provider` | `"default"` | Database provider name |
| `cache` | `None` | Cache provider (takes precedence over `provider`) |
| `schema_name` | `snake_case(cls)` | Table or collection name |
| `database_model` | `None` | Custom database model class |
| `order_by` | `()` | Default field ordering |
| `limit` | `100` | Default query result limit |

Guide: [Projections](../../guides/consume-state/projections.md)

### `Domain.projector`

Maintains projections by reacting to domain events. Uses
`@handle(EventClass)` to process events. Unlike event handlers, projectors
explicitly target a projection and can listen to multiple stream categories.

| Option | Default | Description |
|--------|---------|-------------|
| `projector_for` | `None` | Target projection class |
| `aggregates` | `[]` | Aggregate classes whose events to consume |
| `stream_categories` | derived from `aggregates` | Stream categories to subscribe to |
| `subscription_type` | `None` | Subscription behavior enum |
| `subscription_profile` | `None` | Subscription profile enum |
| `subscription_config` | `{}` | Custom subscription configuration |

Guide: [Projectors](../../guides/consume-state/projectors.md)

### `Domain.process_manager`

A long-running coordinator that reacts to events across multiple aggregates,
maintaining its own state to orchestrate multi-step workflows.

| Option | Default | Description |
|--------|---------|-------------|
| `abstract` | `False` | Cannot be instantiated when `True` |
| `auto_add_id_field` | `True` | Auto-adds an `id` identity field |
| `stream_category` | `snake_case(cls)` | Message stream category |
| `aggregates` | `[]` | Aggregate classes whose events to consume |
| `stream_categories` | derived from `aggregates` | Stream categories to subscribe to |
| `subscription_type` | `None` | Subscription behavior enum |
| `subscription_profile` | `None` | Subscription profile enum |
| `subscription_config` | `{}` | Custom subscription configuration |

Guide: [Process Managers](../../guides/consume-state/process-managers.md)

---

## External Integration

### `Domain.subscriber`

Consumes messages from external message brokers. Subscribers act as an
anti-corruption layer, translating external payloads into domain operations.

| Option | Default | Description |
|--------|---------|-------------|
| **`stream`** | — | **Required.** Broker stream name to subscribe to |
| `broker` | `"default"` | Broker provider name |

Guide: [Subscribers](../../guides/consume-state/subscribers.md)

---

## Persistence

### `Domain.repository`

Persistence abstraction for aggregates. Protean provides a default
repository automatically; custom repositories add domain-specific queries.

| Option | Default | Description |
|--------|---------|-------------|
| **`part_of`** | — | **Required.** Aggregate class being persisted |
| `database` | `"ALL"` | Target database provider(s) |

Guide: [Repositories](../../guides/change-state/repositories.md)

### `Domain.database_model`

Maps a domain element to a specific database schema. Used to customize how
aggregates or entities are stored.

| Option | Default | Description |
|--------|---------|-------------|
| **`part_of`** | — | **Required.** Associated aggregate or entity |
| `database` | `None` | Database type (e.g. `"SQLALCHEMY"`) |
| `schema_name` | from aggregate | Table or collection name |
