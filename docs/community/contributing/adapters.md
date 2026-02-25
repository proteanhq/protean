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

See [Building Custom Database Adapters](../../reference/adapters/database/custom-databases.md)
for a complete guide with a worked DynamoDB example, including:

- The five components to implement (Provider, DAO, DatabaseModel, Lookups,
  Registration)
- Session protocol and call flow diagrams
- How to declare capabilities
- How to test with the conformance suite

## Broker Adapters

Broker adapters implement the `BaseBroker` interface and declare their
capabilities through the `BrokerCapabilities` tier system.

See [Building Custom Brokers](../../reference/adapters/broker/custom-brokers.md)
for a complete guide with a worked Kafka example, including:

- Required abstract methods
- Capability tier selection
- Entry point registration
- Testing patterns

## Event Store and Cache Adapters

Event store adapters extend `BaseEventStore` and implement stream write/read
operations. Cache adapters extend `BaseCache` and implement key-value
operations with TTL support. These follow the same entry-point registration
pattern as database and broker adapters.

## Conformance Testing

Protean provides a generic conformance test suite that validates any database
adapter against its declared capabilities. Use it to verify your adapter
during development and in CI:

```bash
protean test test-adapter --provider=your-adapter-name
```

See [Adapter Conformance Testing](../../reference/testing/conformance.md) for
the full reference.

## Getting Help

- [GitHub Discussions](https://github.com/proteanhq/protean/discussions) --
  Ask questions and share your adapter with the community.
- [Existing adapters](https://github.com/proteanhq/protean/tree/main/src/protean/adapters) --
  Study the built-in implementations for reference.
