# ADR-0049: An adapter port is a Protocol of adapter operations, wrapped by a framework service

**Status:** Accepted

**Date:** November 2026

## Context

Protean reaches four kinds of infrastructure through ports: event stores,
brokers, caches and databases. Before this decision, each port was an abstract
base class, such as `BaseEventStore` or `BaseBroker`, with two jobs. It listed
the operations an adapter writes, and it held the framework features built on
those operations: aggregate loading, retries, dead-letter handling and
unit-of-work recording.

The two jobs pulled the base classes apart:

- An adapter author read the whole base class to find the methods an adapter
  must write. Most of its methods were framework features.
- Adapters took different constructor arguments, and event stores took no
  name.
- Providers and brokers registered through entry points. Event stores and
  caches registered through fixed maps, and an unknown name raised a bare
  `KeyError`.
- Only providers and brokers declared capability flags, so a caller could not
  ask an event store or a cache what it supports.
- Records crossed a port as `dict[str, Any]`, with keys that only the code
  documented.
- Code reached a native client through adapter-specific attributes, and
  `get_connection()` returned `Any` on providers.

This decision keeps four earlier ones:

- [ADR-0023](0023-query-api-conformance-contract-and-capability-tiers.md): a
  capability marker gates each conformance test, and an adapter that declares a
  capability passes every test tagged with it.
- [ADR-0024](0024-event-store-read-position-contract.md) and
  [ADR-0025](0025-all-subscription-gap-safety.md): which positions an
  event-store read returns, and that each category commits in position order.
  The event-store Port keeps both guarantees, and its capability flags name
  them.
- [ADR-0028](0028-partition-per-key-sequential-processing.md): the partition
  contract. Its broker operations form a sub-protocol (decision 4).
- [ADR-0048](0048-sql-event-store.md): the SQL event store implements the
  event-store Port and adds nothing to it.

## Decision

### 1. A port has three parts: a Port, capability flags and a service

- The Port is a `typing.Protocol` that lists the storage or transport
  operations an adapter writes, and nothing else.
- The capability flags declare which optional operations and guarantees an
  adapter supports.
- The service is a concrete framework class that wraps one adapter and builds
  the features on the Port's operations.
- Type hints that refer to an adapter use the Port. Code that needs a feature
  uses the service.
- A port module holds the contract only: the Port, its sub-protocols, its
  capability flags and its typed records. Their docstrings document each
  member, record and flag.

If the Port listed features such as aggregate loading, every adapter would
implement or inherit them, and the base class would return under another name.
In the service, each feature has one implementation that every adapter gets.

### 2. A Port holds no logic

A Port gives a method body only for a no-op, such as `create_schema()` on a
store with no schema. The body is `return None` (or the empty value of the
return type), because mypy treats a Protocol method whose body is `...` as
abstract. Retry policy, TTL defaults, aggregate loading and unit-of-work
binding live in the service.

A no-op default fits only an operation whose absence changes no outcome for the
caller. An operation whose absence the caller needs to know about, such as
trimming a stream to a retention limit, is a sub-protocol behind its own flag
(decision 4), so the service can see that the adapter lacks it.

### 3. An adapter subclasses its Port, and strict mypy checks it

- An adapter class subclasses its Port explicitly, as PEP 544 allows.
- Each required member is an `@abstractmethod`. Python refuses to build an
  incomplete adapter, and the registry names the missing members when it first
  loads the class.
- Each adapter module ends with a typed assignment, such as
  `_PORT_CHECK: type[EventStorePort] = MemoryEventStore`. Mypy does not report
  a missing member at the class definition. It reports it at this assignment,
  and fails in strict mode.
- A model class whose metaclass conflicts with `Protocol` does not subclass its
  Port. The typed assignment checks it structurally.
- No Port is `runtime_checkable`.

A runtime `isinstance` check against a Protocol compares method names and
ignores signatures. Explicit subclassing gives Python's check for missing
members and mypy's check of signatures.

### 4. A declared flag requires its sub-protocol

- An optional feature with its own methods is a sub-protocol of the Port,
  unlocked by one capability flag, such as `DeadLetterQueuePort` for
  `DEAD_LETTER_QUEUE`.
- A flag without a sub-protocol declares a guarantee, such as durability, or
  gates members or arguments of the core Port, such as the schema operations
  behind `SCHEMA_MANAGEMENT`.
- An adapter that declares a flag implements every member of the flag's
  sub-protocol. The service checks this when it is built, because
  `capabilities` is a property of the adapter instance, and raises
  `ConfigurationError` naming the flag and the class.
- The check runs one way. A class may implement a sub-protocol without
  declaring its flag, because one class can serve several databases with
  different capabilities.
- A service method that needs a feature checks the flag first. Without the
  flag, it falls back to core Port operations, returns the empty value, or
  raises `NotSupportedError`, as its docstring states. A blocking read, for
  example, falls back to an ordinary read that returns the messages available.

### 5. Every port declares capability flags, and every flag gates a test

- Event stores and caches gain capability flags. Each flag set follows the
  broker's: individual flags, then named tiers.
- A check reads the flag directly:
  `EventStoreCapabilities.EXPECTED_VERSION in adapter.capabilities`. The
  `has_capability`, `has_all_capabilities` and `has_any_capability` helpers are
  removed.
- Each flag gates at least one conformance test. An adapter that declares a
  flag and fails that flag's tests fails the suite.

A flag that no test checks can be wrong while every test passes. A flag enum
supports `in`, so the helpers were a second way to write the same check.

### 6. Containers return services

- `domain.event_store`, `domain.brokers[name]`, `domain.caches[name]` and
  `domain.providers[name]` each return a service.
- Every service exposes its adapter as `.adapter`, typed with the Port.
- The services are `EventStore`, `Broker`, `Cache`, `Provider` and `DAO`.
- A domain has one event store, so `domain.event_store` is the `EventStore`
  service. Brokers, caches and providers keep their containers: `Brokers`,
  `Caches` and `Providers`.

Callers reach every framework feature through one object, and code that needs
adapter internals shows it by reading `.adapter`.

### 7. Services, containers and the registry live in `protean.infra`

`protean.infra` holds the services, the containers and the adapter registry, in
flat modules. `protean.adapters` holds adapter implementations only.

The `protean check` diagnostic that reports a domain module importing
`protean.adapters` then flags infrastructure imports alone.
`protean.domain.infrastructure` keeps its name and its job, database and outbox
setup.

### 8. Registered adapters share one constructor and one registry

- Every event store, broker, cache and provider is built as
  `__init__(self, name: str, domain: Domain, config: Mapping[str, Any])`.
  `config` replaces `conn_info`. An event store's name is `default`, because a
  domain has one.
- DAO and lookup classes are not registered, and keep their own constructors.
- One generic registry class serves all four ports. It reads the entry-point
  groups `protean.providers`, `protean.brokers`, `protean.event_stores` and
  `protean.caches`.
- On first load, the registry checks a class for missing abstract members and
  raises `ConfigurationError` naming them. An unknown name raises
  `ConfigurationError` that lists the registered names.

Built-in and outside adapters register the same way, and an adapter author
writes one constructor shape for every port.

### 9. Records with fixed fields cross a Port as typed values

- A record with fixed fields, such as an event-store row, a broker message or a
  dead-letter entry, is a `TypedDict`, a `NamedTuple` or a dataclass.
- A free-form value keeps a mapping of `Any`: a message payload, event data and
  metadata, a cached value, adapter-specific configuration.
- Every port's `health()` returns a dataclass. The event-store, cache and
  provider records share one connection-pool record, or `None` for an adapter
  without a pool. The broker record types the fields brokers report, and the
  `Broker` service wraps it in its health envelope.

Mypy checks every field a caller reads. One record kind across the ports lets
the health endpoints and the observatory read every port the same way.

### 10. `get_connection()` returns `object`

Each adapter returns its native handle: a SQLAlchemy session, an Elasticsearch
client, a Redis client, a Message DB client, or `None` for an adapter without
one. A caller narrows the result with `isinstance`. `get_connection()` replaces
the adapter-specific attributes, such as the Message DB store's `client` and
the Redis broker's `redis_instance`.

No common type covers these handles. `Any` would let a caller use the handle
without narrowing it, and mypy would not report a wrong assumption.

### 11. Names follow four rules

- A Port member's name is in snake case with no leading underscore. An
  operation's name is a verb and an object where one fits.
- One concept has one name across every port. Arguments come in one order: the
  stream or key, then the group, then options. `limit` is the name for a count
  of messages or rows. The exceptions: `ack`, `nack` and `ack_partition_fenced`
  put the message ID between the stream and the group, `trim` takes `maxlen`,
  the name of the `retention_maxlen` setting it serves, and the `EventStore`
  service's `read_all` takes `page_size`, because it sets the size of each
  page.
- The event-store Port uses Message DB's function names where they exist, such
  as `write_message` and `get_stream_messages`, and has one read member per
  scope: stream, category and all. The caller states the scope by the member it
  calls, and the adapter does not infer it from the stream name. The service
  computes a stream's version and a category's head position from the
  last-message reads.
- The event-store, broker, cache and provider Ports share one set of
  lifecycle members, with the same names on every Port: the adapter's name and
  capabilities, a liveness check, a health record, the native handle, closing
  the adapter, and clearing its data. A Port whose adapter can own a schema adds
  schema creation and removal, behind a `SCHEMA_MANAGEMENT` flag.

### 12. Conformance suites live in the repository

Each port's conformance suite lives under `tests/conformance/<port>/` and stays
out of the wheel. `protean test test-adapter --port <port>` runs it from a
source checkout. One pytest plugin selects the adapter for every port, and a
test declares the flag it needs with one marker, which the plugin reads against
the adapter's declared capabilities.

One plugin and one marker give every port the same way to select an adapter
and skip a test.

### 13. The port break follows the stable-surface tiers

- The `Base*` adapter classes are removed. Code that the adapters of one
  technology share stays in that technology's adapter package, as the
  SQLAlchemy dialects share one provider class. `BaseDatabaseModel` stays as
  the base for model classes.
- A Provisional or Internal name in `docs/reference/stable-surface.md`, such as
  a port base class or the broker partition contract, changes in a minor
  release without a deprecation shim. Each change a caller can reach gets a
  changelog entry and a migration-guide entry.
- A Stable name, such as a documented option of the conformance plugin, keeps
  working with a `DeprecationWarning` that names its removal version, as
  [ADR-0004](0004-release-workflow-and-breaking-change-policy.md) requires.

## Consequences

**Positive:**

- An adapter author implements one Port and the sub-protocols of the flags they
  declare. The Port lists every member they write, and mypy reports a missing
  one.
- An incomplete adapter fails when it is loaded or when its service is built,
  with an error that names the missing members or the flag.
- Each framework feature has one implementation, in the service, and every
  adapter gets it.
- A caller can ask any adapter what it supports, and a test backs each flag.
- Mypy checks the fields callers read from records and the narrowing of native
  handles.
- Built-in and outside adapters register through the same registry.

**Negative:**

- Every adapter, container and test fixture changes. An adapter maintained
  outside Protean is rewritten against its Port.
- Each port has two classes, the adapter and the service, and code that needs
  adapter internals goes through `.adapter`.
- A model class whose metaclass conflicts with `Protocol` gets mypy's
  structural check only. Python does not refuse an incomplete one.
- Mypy does not compare an adapter's `__init__` with the Port's.
- A declared flag without its sub-protocol fails when the service is built,
  after the adapter class has loaded.
- A caller narrows the result of `get_connection()` before using it.

## Alternatives Considered

- **Keep the abstract base classes and trim them.** Rejected: the features stay
  inherited, and every adapter carries them.
- **Use `runtime_checkable` Protocols with `isinstance` checks.** Rejected: a
  runtime check compares method names only, so a member with the wrong
  signature passes.
- **Give the Port a no-op default for every optional operation.** Rejected: a
  no-op hides a limit the adapter ignores, such as a stream retention limit.
- **Put stream trimming in the partitioning sub-protocol.** Rejected: retention
  and partitioning are independent, and an adapter that only trims would write
  the lease members.
- **Type `get_connection()` as `Any`.** Rejected: mypy would not report a
  caller that uses the handle without narrowing it.
- **Put the services in `protean.services`.** Rejected: "service" already
  names domain services and application services in Protean.
- **Put each service in its adapter package under `protean.adapters`.**
  Rejected: the package would mix the framework with the adapters it wraps, and
  the `protean check` diagnostic on `protean.adapters` imports would flag
  framework imports.
- **Keep deprecation shims for the renamed port methods.** Rejected: the port
  classes are Provisional, so the stable-surface policy lets them change in a
  minor release, and the migration guide gives each caller the new name.
