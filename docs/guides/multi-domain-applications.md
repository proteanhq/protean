# Multi-Domain Applications

A large system usually has more than one bounded context, and in Protean each
one is a separate `Domain` instance. Here is how to structure an application
that way. For the conceptual foundation, see [Bounded Contexts](../concepts/foundations/bounded-contexts.md).

---

## When to use multiple domains

Use separate domains when your application has:

- **Distinct vocabularies:** "Customer" in billing means something different
  from "Customer" in shipping
- **Independent lifecycles:** The catalog team deploys weekly; the billing
  team deploys monthly
- **Different infrastructure needs:** Orders need PostgreSQL; analytics
  needs Elasticsearch
- **Organizational boundaries:** Separate teams own separate contexts

If your entire application shares one ubiquitous language and one team
maintains it, a single domain is simpler and sufficient.

---

## Project structure

Organize each bounded context as a separate Python package with its own
domain instance, configuration, and elements:

```
my_app/
├── identity/
│   ├── __init__.py          # identity_domain = Domain(name="Identity")
│   ├── domain.toml          # Identity-specific config
│   ├── customer.py          # Customer aggregate
│   ├── events.py            # CustomerRegistered, etc.
│   └── handlers.py          # Identity command/event handlers
├── catalogue/
│   ├── __init__.py          # catalogue_domain = Domain(name="Catalogue")
│   ├── domain.toml
│   ├── product.py           # Product aggregate
│   └── handlers.py
├── fulfillment/
│   ├── __init__.py          # fulfillment_domain = Domain(name="Fulfillment")
│   ├── domain.toml
│   ├── shipment.py          # Shipment aggregate
│   ├── subscribers.py       # Consumes events from other domains
│   └── handlers.py
└── api/
    └── app.py               # FastAPI app wiring all domains together
```

Each domain's `__init__.py` creates its own `Domain` instance:

```python
--8<-- "guides/multi-domain-applications/001.py:domains"
```

---

## Independent configuration

Each domain can have its own `domain.toml` with separate database, broker,
and event store settings:

```toml
# my_app/identity/domain.toml
[databases.default]
provider = "postgresql"
database_uri = "postgresql://localhost/identity_db"

[brokers.default]
provider = "redis"
URI = "redis://localhost:6379/0"
```

```toml
# my_app/catalogue/domain.toml
[databases.default]
provider = "elasticsearch"
database_uri = "http://localhost:9200"

[brokers.default]
provider = "redis"
URI = "redis://localhost:6379/1"
```

Alternatively, pass configuration programmatically:

```python
# fragment
identity_domain = Domain(
    name="Identity",
    config={
        "databases": {
            "default": {
                "provider": "postgresql",
                "database_uri": "postgresql://localhost/identity_db",
            }
        }
    },
)
```

---

## Wiring domains in FastAPI

Use `DomainContextMiddleware` to route HTTP requests to the correct domain
context based on URL prefix:

```python
--8<-- "guides/multi-domain-applications/001.py:fastapi-app"
```

Requests to `/customers/...` automatically activate `identity_domain`;
requests to `/products/...` activate `catalogue_domain`, and so on.
Requests that don't match any prefix (e.g. `/health`) pass through without
a domain context.

---

## Cross-domain communication

Domains communicate through events, never by importing each other's
aggregates or calling each other's services directly. Protean supports
two integration paths, and the right choice depends on the **strategic
relationship** between the bounded contexts.

### Choosing the right integration path

| | Co-located domains | Distributed domains |
|---|---|---|
| **Deployment** | Same repo, same process | Separate services, independent deploys |
| **Schema ownership** | You control both sides; changes are visible in one codebase | Upstream can change independently |
| **Integration mechanism** | `register_external_event()` with typed event classes | Subscribers as anti-corruption layers (raw `dict` payloads) |
| **Best for** | Process managers coordinating cross-domain workflows; event handlers syncing state across co-located contexts | Independent services, external systems, webhook ingestion |
| **DDD pattern** | Conformist / Published Language | Anti-Corruption Layer |

!!!tip
    This is not an either-or choice at the project level. A single application
    can use both paths, `register_external_event` for tightly coordinated domains in the same repo,
    and subscribers for external systems you don't control.

### Co-located domains: Registered external events

When multiple domains live in the same repository and share the same event
store, use `register_external_event()` to give your domain typed access to
another domain's events. This is especially useful for **process managers**
that coordinate workflows spanning multiple bounded contexts.

```python
--8<-- "guides/multi-domain-applications/001.py:external-events"
```

Now process managers and event handlers can use these typed events directly:

```python
--8<-- "guides/multi-domain-applications/001.py:process-manager"
```

`on_stock_reserved` completes the process only when the order is waiting for
stock, so it calls `mark_as_complete()` inside its guard. `end=True` would
complete the process even on the early return. `on_stock_unavailable` ends the
process in any state, so it uses `end=True`.

**Why this works for co-located domains:**

- You control both sides of the schema. Changes are visible in one codebase
  and can be coordinated in a single pull request.
- Typed events give you IDE support, static analysis, and deserialization
  validation, no parsing raw dicts.
- The PM subscribes to external streams directly, keeping the coordination
  logic concise and traceable.

**Important:** The external event class is defined *in your domain*, not
imported from the other domain's package. You own the class; the type
string (`"Billing.PaymentReceived.v1"`) is the shared contract.

For syncing state across co-located contexts (without a process manager),
you can also use event handlers with `stream_category`:

```python
--8<-- "guides/multi-domain-applications/001.py:event-handler"
```

### Distributed domains: Subscribers as anti-corruption layers

When domains run as independent services with separate brokers (or when you
consume events from external systems you don't control) use subscribers.
Subscribers receive raw `dict` payloads and translate them into your domain's
language, acting as an anti-corruption layer:

```python
--8<-- "guides/multi-domain-applications/001.py:subscriber"
```

**Why this works for distributed domains:**

- **Schema isolation**: Your domain doesn't depend on the external
  domain's event classes. If the upstream renames a field, only the
  subscriber changes.
- **Translation at the boundary**: External field names, types, and
  concepts are mapped to your domain's language before entering the
  domain.
- **Independent evolution**: The upstream can deploy schema changes
  without coordinating with you. The subscriber absorbs the difference.

Key principles:

- **Subscribers receive `dict`, not typed events**: Your domain doesn't
  import the external domain's classes
- **Translate at the boundary**: Map external field names, types, and
  concepts to your domain's language
- **Everything downstream uses internal types**: Only the subscriber knows
  about the external schema

See [Consuming Events from Other Domains](../patterns/consuming-events-from-other-domains.md)
for the full pattern.

### Fact events for state transfer

When an external consumer needs complete aggregate state (not granular
deltas), enable fact events on the source aggregate:

```python
--8<-- "guides/multi-domain-applications/002.py:fact-events"
```

Fact events publish a full snapshot with every change, making downstream
consumers simpler. They replace their local copy wholesale instead of applying
incremental updates.

See [Fact Events as Integration Contracts](../patterns/fact-events-as-integration-contracts.md).

---

## Correlation across contexts

The same real-world entity (e.g. a customer) often appears in multiple
bounded contexts with different names and shapes. Link them using a shared
identifier:

```python
--8<-- "guides/multi-domain-applications/001.py:correlation"
```

The `customer_id` in `Recipient` is a correlation ID. It links back to the
authoritative `Customer` in the identity context without creating a code
dependency.

See [Connecting Concepts Across Bounded Contexts](../patterns/connect-concepts-across-domains.md).

---

## Running multiple domain servers

Each domain runs its own server process for async event/command processing:

```bash
# Terminal 1
protean server --domain my_app.identity

# Terminal 2
protean server --domain my_app.catalogue

# Terminal 3
protean server --domain my_app.fulfillment
```

### Monitoring across domains

The observatory supports monitoring multiple domains simultaneously:

```bash
protean observatory \
    --domain my_app.identity \
    --domain my_app.catalogue \
    --domain my_app.fulfillment
```

---

## Testing multi-domain applications

### Separate fixtures per domain

Create independent test fixtures for each domain:

```python
--8<-- "guides/multi-domain-applications/001.py:fixtures"
```

### Testing cross-domain flows

In tests the domains run in sync mode, and a domain in sync mode runs only its
own handlers. An event raised in the identity domain never reaches a
fulfillment handler, so a test cannot follow a flow across the boundary. Test
each side of the boundary instead. On the receiving side, hand the event the
other domain publishes to your handler, and check the effect in your domain:

```python
--8<-- "guides/multi-domain-applications/001.py:cross-domain-test"
```

To run a flow end to end across domains, run each domain's engine against a
shared event store, as in production.

### Testing FastAPI endpoints across domains

```python
--8<-- "guides/multi-domain-applications/001.py:api-tests"
```

---

## Design guidelines

1. **Start with one domain**: Split only when you observe genuine language
   divergence or team boundaries. Premature splitting adds complexity
   without benefit.

2. **Each domain owns its data**: Domains should not share databases. If two
   domains need the same data, one is the authority and the other holds a
   local copy synchronized through events.

3. **Communicate through events, not imports**: Never import an aggregate
   from another domain's package. Use subscribers or cross-stream event
   handlers to react to changes.

4. **Translate at boundaries**: Use the anti-corruption layer pattern
   (subscribers) to translate external concepts into your domain's language.

5. **Deploy independently when possible**: Each domain should be deployable
   on its own schedule. Shared deployment couples teams and slows everyone
   down.
