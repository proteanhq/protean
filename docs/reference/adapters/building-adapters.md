# Building Adapters

Protean's adapter architecture is designed for extensibility. Third-party
packages can add new database providers, message brokers, event stores, and
cache backends without modifying Protean's source code.

## How It Works

All adapter types use Python
[entry points](https://packaging.python.org/en/latest/specifications/entry-points/)
for registration. When you `pip install` a package that defines the appropriate
entry point, Protean automatically discovers and makes the adapter available
for configuration.

Each adapter package provides:

1. An **implementation** that extends the relevant base class
2. A **`register()` function** that registers the adapter with Protean's
   registry
3. An **entry point** in `pyproject.toml` that points to the `register()`
   function

## Database Adapters

Database adapters implement the `BaseProvider` interface and declare their
capabilities through the `DatabaseCapabilities` flag system.

See [Building Custom Database Adapters](./database/custom-databases.md)
for a complete guide with a worked DynamoDB example, including:

- The five components to implement (Provider, DAO, DatabaseModel, Lookups,
  Registration)
- Session protocol and call flow diagrams
- How to declare capabilities
- How to test with the conformance suite

## Broker Adapters

Broker adapters implement the `BaseBroker` interface and declare their
capabilities through the `BrokerCapabilities` tier system.

See [Building Custom Brokers](./broker/custom-brokers.md)
for a complete guide with a worked Kafka example, including:

- Required abstract methods
- Capability tier selection
- Entry point registration
- Testing patterns

## Event Store and Cache Adapters

Event store adapters extend `BaseEventStore`, implement stream write/read
operations, and declare the guarantees they make on a `capabilities` property.
See [What each event store guarantees](./eventstore/index.md#what-each-event-store-guarantees).
Cache adapters subclass the `CachePort` protocol, implement its key-value
operations, and declare their capabilities through `CacheCapabilities`. An
adapter that declares `TTL` also subclasses `CacheTTLPort`, and one that declares
`PATTERN_MATCH` also subclasses `CachePatternPort`. `Domain.init()` raises
`ConfigurationError` when an adapter declares `TTL` or `PATTERN_MATCH` and does
not subclass the matching protocol.

They register the same way as database and broker adapters. An event store's
`register()` function calls `protean.infra.registry.event_stores`, and its entry
point goes in the `protean.event_stores` group. A cache uses
`protean.infra.registry.caches` and the `protean.caches` group:

```python
# fragment
# src/protean_eventstoredb/__init__.py
def register():
    """Register the EventStoreDB event store with Protean."""
    from protean.infra.registry import event_stores

    event_stores.register(
        "eventstoredb", "protean_eventstoredb.store.EventStoreDBStore"
    )
```

```toml
# fragment
[project.entry-points."protean.event_stores"]
eventstoredb = "protean_eventstoredb:register"
```

The `provider` key in `[event_store]` or `[caches.<name>]` then selects the
adapter by that name. An event store class takes `(domain, conn_info)` in its
constructor. A cache class takes `(name, domain, config)`, where `config`
is the cache's table from the domain configuration.

When `Domain.init()` loads the class, the registry checks that the class
implements every abstract method and property it inherits. If any are missing,
the registry raises `ConfigurationError` and names each one. The registry does
not check that the class subclasses the port's base class.

Protean loads every entry point in a group the first time it looks up a name in
that group. If your code registers a name before then, and an installed package
also declares that name, the entry point replaces your class path and Protean
logs a warning. Use a name no installed package declares.

## Conformance Testing

Protean provides a conformance test suite for each port that validates an
adapter against its declared capabilities. Use it to verify your adapter
during development and in CI, from a Protean source checkout:

```bash
protean test test-adapter --provider=your-adapter-name
protean test test-adapter --port=broker --provider=your-broker-name
```

`--port` is `database` (the default), `broker`, `cache` or `event_store`.

See [Adapter Conformance Testing](../testing/conformance.md) for
the full reference.

## Getting Help

- [GitHub Discussions](https://github.com/proteanhq/protean/discussions):
  Ask questions and share your adapter with the community.
- [Existing adapters](https://github.com/proteanhq/protean/tree/main/src/protean/adapters):
  Study the built-in implementations for reference.
