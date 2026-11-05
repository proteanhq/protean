# ADR-0049: Each adapter port is a Protocol that lists adapter operations, wrapped by a framework service

**Status:** Accepted

**Date:** November 2026

## Context

Protean talks to four kinds of infrastructure through ports: event stores,
brokers, caches and databases. A port today is an abstract base class, such as
`BaseEventStore` or `BaseBroker`, that mixes two jobs. It lists the operations
an adapter must write, and it holds framework features built on those
operations, such as aggregate loading, retries, dead-letter handling and
unit-of-work recording.

The two jobs have grown apart:

- `BaseEventStore` has 41 methods, and the two event stores override 7 of
  them besides `__init__`. `BaseBroker` has 57 methods, and the three brokers
  override 25 of them besides `__init__`. An
  adapter author has to read the whole class to find the methods they must
  write.
- Adapters take more than one constructor shape. Providers, brokers and caches
  take `(name, domain, conn_info)`, while `MemoryEventStore` and
  `MessageDBStore` take `(domain, conn_info)`.
- Adapters register through two paths. Providers and brokers use entry-point
  groups. Event stores and caches use hard-coded maps, and an unknown name
  raises a bare `KeyError`.
- Only providers and brokers declare capability flags. Event stores and caches
  declare nothing, so a service cannot tell what an adapter supports.
- Records cross a port as `dict[str, Any]`. An event-store row, a broker
  message and a health report each have keys that only the code documents.
- `get_connection()` returns `Any` on providers and `object` on caches. The
  Message DB store exposes its client as `client`, and the observatory reads
  `redis_instance` off a broker.

Four earlier ADRs still hold:

- [ADR-0023](0023-query-api-conformance-contract-and-capability-tiers.md)
  defines the conformance contract: a capability marker gates each conformance
  test, and an adapter that declares a capability must pass every test tagged
  with it. The new event-store and cache flags follow that contract.
- [ADR-0028](0028-partition-per-key-sequential-processing.md) defines the
  partition contract. `PartitioningPort` lists its broker operations.
- [ADR-0024](0024-event-store-read-position-contract.md) fixes which positions
  a read returns, and
  [ADR-0025](0025-all-subscription-gap-safety.md) relies on each category
  committing in position order. The event-store Port keeps both guarantees, and
  two capability flags name them.

Each port sub-issue of epic
[#2050](https://github.com/proteanhq/protean/issues/2050) decides the names
for one port. The Decision below states the shape all ports share, and its
tables gather every decided name. Every name is copied from the sub-issue that
decides it. Where two sub-issues disagree, or a member has no deciding
sub-issue, the conflict is listed under
[Four conflicts wait for a ruling](#19-four-conflicts-between-sub-issues-wait-for-a-ruling).

## Decision

### 1. A port has three parts: a Port, capability flags and a service

The Port is a `typing.Protocol` that lists the storage or transport operations
an adapter writes, and nothing else. The capability flags declare which
optional operations an adapter supports. The service is a concrete framework
class that wraps one adapter and builds the features on the Port's operations.

The Port lists only adapter operations. If it listed features such as
`load_aggregate` or `verify`, every adapter would have to implement or inherit
them, and an inherited base class would come back under another name. Template
methods on base classes become composition: the service calls the adapter.

Type hints that refer to an adapter use the Port. Registries, containers and
service attributes are typed with the Port. A caller that needs a feature uses
the service, which has one implementation.

Each port module holds the contract only: the Port, its sub-protocols, the
capability flag and the typed records. The database contract stays in two
modules, `src/protean/port/provider.py` and `src/protean/port/dao.py`, and
`port/dao.py` is not split.

### 2. An adapter subclasses its Port, and its module checks it with a typed assignment

PEP 544 allows a class to subclass a Protocol explicitly. Mypy does not report
a missing member at the class definition. It reports one where the class is
assigned to a `type[<Port>]` variable. So each adapter module ends with an
assignment such as:

```python
_PORT_CHECK: type[EventStorePort] = MemoryEventStore
```

Mypy in strict mode fails at that line when a member is missing. A module that
holds adapters of several Ports has one check per Port, because mypy rejects a
second annotated `_PORT_CHECK` in one module: `_PORT_CHECK` checks the
provider, `_MODEL_PORT_CHECK` the database model and `_DAO_PORT_CHECK` the DAO.

`SqlalchemyModel` and `ElasticsearchModel` already have a metaclass that
conflicts with `Protocol`. These two classes do not subclass the Port, and the
same assignment checks them structurally.

While a `Base*` class remains during the migration, an adapter lists it first,
as in `class RedisBroker(BaseBroker, BrokerPort)`. With the Port first, an
adapter that defines no `__init__` of its own would get the Port's stub
`__init__` instead of the base class's, with no error.

### 3. Required Port members are abstract, and no Port is `runtime_checkable`

Every required method is an `@abstractmethod`, so Python refuses to build an
incomplete adapter. The registry rejects an incomplete class when it first
loads it, and names the missing methods from `__abstractmethods__`.

`__init__` and the attribute members, such as `name`, `domain` and `config`,
are outside this rule. `__init__` is not abstract, and `__abstractmethods__`
holds methods and properties only, so the registry check does not cover
attributes.

The Ports are not `runtime_checkable`. A runtime `isinstance` check against a
Protocol sees method names only, not signatures. Code that must know whether a
class implements a sub-protocol reads `type(adapter).__mro__`.

### 4. A Port holds no logic, and a no-op default is written `return None`

A Port gives a method body only for a no-op, such as `create_schema()` on an
adapter with no schema. Retry policy, TTL defaults, aggregate loading and
unit-of-work binding live in the service.

A no-op default writes `return None` (or `return 0`, `return nullcontext()`
where the return type needs it). Mypy treats a Protocol method whose body is
`...` as abstract, so a default written that way would make every adapter
abstract.

### 5. A declared flag requires its sub-protocol, checked when the service is built

A declared capability flag requires every member of the sub-protocol it
unlocks. The service runs this check when it is built, because
`capabilities` is a property of the adapter instance and the registry holds
only the class. A missing member raises `ConfigurationError` that names the
flag and the class.

The check runs one way. A class may implement a sub-protocol without declaring
its flag, because one class can serve several databases with different
capabilities. `SADAO` implements `NativeClaimPort` and `BoundedDeletePort` for
every SQL dialect, while `MysqlProvider` declares neither flag.

### 6. The `Base*` adapter classes are removed

`BaseEventStore`, `BaseBroker`, `BaseCache`, `BaseProvider`, `BaseDAO` and
`BaseLookup` are removed once their Port and service exist. Code that the
adapters of one technology share stays in that adapter's package, as the
SQLAlchemy dialects already share `SAProvider`. `BaseDatabaseModel` stays as
the base for model classes, and `RegisterLookupMixin` stays.

### 7. An optional feature with its own methods is a sub-protocol unlocked by one flag

A capability flag in the table below unlocks a sub-protocol that types the
feature's methods. The
flag declares the feature. A service method that needs the feature checks the
flag, and raises `NotSupportedError` or returns the empty value when the
adapter lacks it, as the service tables below state.

Each port keeps one flag-to-sub-protocol table:

| Port | Flag | Sub-protocol | Decided in |
|------|------|--------------|------------|
| Broker | `BLOCKING_READ` | `BlockingReadPort` | #2070 |
| Broker | `DEAD_LETTER_QUEUE` | `DeadLetterQueuePort` | #2071 |
| Broker | `STREAM_PARTITIONING` | `PartitioningPort` | #2072 |
| Broker | `STREAM_RETENTION` | `StreamRetentionPort` | #2072 |
| Cache | `TTL` | `CacheTTLPort` | #2066 |
| Cache | `PATTERN_MATCH` | `CachePatternPort` | #2066 |
| Provider | `RAW_QUERIES` | `RawQueryProviderPort` | #2076, #2085 |
| DAO | `RAW_QUERIES` | `RawQueryDAOPort` | #2080 |
| DAO | `NATIVE_CLAIM` | `NativeClaimPort` | #2079, #2080 |
| DAO | `FILTERED_CLAIM_CANDIDATES` | `ClaimCandidatesPort` | #2079, #2080 |
| DAO | `BOUNDED_DELETE` | `BoundedDeletePort` | #2079, #2080 |
| DAO | `INSERT_IF_ABSENT` | `InsertIfAbsentPort` | #2080 |

A flag outside this table unlocks no sub-protocol. It declares a guarantee,
or it gates members of the core Port. Three of these cases need a note:

- `SCHEMA_MANAGEMENT`, on event stores and providers, guards `create_schema`
  and `drop_schema`, which are no-op defaults on the core Port.
- The event-store `CONSUMER_GROUPS` flag gates the `consumer_group_member` and
  `consumer_group_size` arguments of `get_category_messages`.
- The broker flags `PUBLISH`, `SUBSCRIBE`, `CONSUMER_GROUPS`, `ACK_NACK`,
  `DELIVERY_GUARANTEES`, `MESSAGE_ORDERING` and `REPLAY` have no
  sub-protocol. They declare operations on `BrokerPort` or delivery
  guarantees.

`DAOPort` has no `capabilities` member. The DAO flags are
`DatabaseCapabilities` flags, and the `DAO` service reads them from
`provider.capabilities`.

The broker table is `SUB_PROTOCOLS: dict[BrokerCapabilities, type[BrokerPort]]`
in `src/protean/port/broker.py`, as #2070 writes it. Conflict 1 under
[Four conflicts wait for a ruling](#19-four-conflicts-between-sub-issues-wait-for-a-ruling)
concerns its value type. The members it checks for a flag are the
sub-protocol's `__abstractmethods__` minus `BrokerPort.__abstractmethods__`, so
the table needs no second list of names. The cache table lives in
`src/protean/port/cache.py`. The provider and DAO checks read
`type(adapter).__mro__`.

### 8. Every container returns services, and every service exposes `.adapter`

`domain.event_store`, `domain.brokers[name]`, `domain.caches[name]` and
`domain.providers[name]` each return a service. Every service exposes its
adapter as `.adapter`, typed with the Port. Test fixtures that return an
adapter today return the service, and a test that needs adapter internals reads
`.adapter`.

### 9. Records cross a Port as typed values

The records listed under [Typed records](#typed-records) below replace
`dict[str, Any]` arguments and results with a `TypedDict`, a `NamedTuple` or a
dataclass, following `DLQEntry`. Free-form values keep a dict or mapping of
`Any`: the message passed to `publish`, the data and metadata of
`write_message`, the values of `update_all`, `BrokerHealth.configuration` and
`CacheEntry`.

Every `<Port>Health` record is a dataclass. `EventStoreHealth`, `CacheHealth`
and `ProviderHealth` carry `pool: PoolStats | None`, and an adapter without a
connection pool returns `pool=None`. `PoolStats` lives in
`src/protean/port/health.py`. `BrokerHealth` types the fields that the three
brokers return from `_health_stats` today, and carries no `pool` field. One
record kind across the ports lets `utils/health.py` and the observatory read
every port the same way.

The `Broker` service keeps the envelope it builds today (`status`,
`connected`, `last_ping_ms`, `uptime_seconds`, `details`) and puts the
adapter's record in `details`.

### 10. The four registered kinds of adapter share one constructor

Every event store, broker, cache and provider is built as
`__init__(self, name: str, domain: Domain, config: Mapping[str, Any])`. The
registry builds each of them through it. `conn_info` becomes `config` on all
four ports.

DAO and lookup adapters are not registered, and keep their own constructors.
Today `BaseDAO` takes `(domain, provider, entity_cls, database_model_cls)`.
After #2080, an adapter DAO is built as
`(provider, entity_cls, database_model_cls)`, and the `DAO` service holds the
domain. A lookup is built as `(source, target, *, database_model_cls=None)`.

### 11. One registry class serves all four ports

`AdapterRegistry[PortT]` in `src/protean/infra/registry.py` replaces
`ProviderRegistry`, `BrokerRegistry`, `EVENT_STORE_PROVIDERS` and
`CACHE_PROVIDERS`. It has four instances, `providers`, `brokers`,
`event_stores` and `caches`, reading the entry-point groups
`protean.providers`, `protean.brokers`, `protean.event_stores` and
`protean.caches`.

On the first `get()` of a name, the registry checks the class against
`__abstractmethods__` and raises `ConfigurationError` naming the missing
methods. Each instance may pass an `after_load` check: the provider instance
rejects a provider whose `get_lookups()` lacks a name in `REQUIRED_LOOKUPS`. An
unknown name raises `ConfigurationError` that lists the registered names.

### 12. Services and containers live in flat modules in `src/protean/infra/`

The modules are `event_store`, `cache`, `broker`, `provider`, `dao`,
`dao_read`, `dao_write`, `dao_tracking`, `causation`, `integrity`, and
`registry` for the adapter registry.

The service classes are `EventStore`, `Broker`, `Cache`, `Provider` and `DAO`.
The containers keep their names, `Brokers`, `Caches` and `Providers`, and the
domain keeps one `EventStore`. Each port's service sub-issue moves that port's
container into `protean.infra`: #2058 moves `EventStore`, #2066 moves
`Caches`, #2069 moves `Brokers` and #2085 moves `Providers`.

`protean.adapters` then holds adapter implementations only. The `protean
check` diagnostic that reports a domain module importing `protean.adapters`
(defined in `src/protean/ir/diagnostics.py` and matched in
`src/protean/ir/builder.py`) keeps its meaning.

`protean.domain.infrastructure` keeps its name. It is a module inside
`protean.domain`, and its job (database and outbox setup) is unchanged.

The method list each service keeps is under
[Service method lists](#service-method-lists) below.

### 13. Names follow four rules

- A Port member's name is in snake case, with no leading underscore. An
  operation's name is a verb and an object where one fits.
- One concept has one name across every port. Arguments come in one order: the
  stream or key, then the group, then options. `limit` is the name for a count
  of messages or rows. The broker sub-issues keep three exceptions: `ack`,
  `nack` and `ack_partition_fenced` put the message ID between the stream and
  the group, and `trim` takes `maxlen`, the name of the `retention_maxlen`
  setting it serves. The `EventStore` service's `read_all` takes `page_size`,
  because it sets the size of each page, not a total.
- The event-store Port uses Message DB's function names where they exist:
  `write_message`, `get_stream_messages`, `get_category_messages`,
  `get_last_stream_message`. One read member per scope (stream, category, all)
  replaces the scope that `_read` guesses from the stream name. A stream's
  version and a category's head position follow from the last-message reads,
  so the service computes them. The cache Port uses `get`, `put` and `delete`,
  with a `_matching` form for patterns.
- The event-store, broker, cache and provider Ports each have `name`,
  `capabilities`, `ping()`, `health()`, `get_connection()`, `close()` and
  `clear()`. `DAOPort`, `LookupPort` and `DatabaseModelPort` have none of
  these. `clear()` replaces `_data_reset`
  and `flush_all`. `create_schema()` and `drop_schema()` are on the provider
  and event-store Ports only, behind a `SCHEMA_MANAGEMENT` flag.

### 14. `get_connection()` returns `object`

Each adapter returns its native handle from `get_connection()`: a SQLAlchemy
`Session`, the memory store's `MemorySession`, the `Elasticsearch` client, a
`redis.Redis` client or a Message DB client. No common type covers these
handles. A caller narrows the result with `isinstance`. `InlineBroker`
returns `None`.

Today nine places in `src/protean/server` probe a broker with
`hasattr(broker, "redis_instance")`, and two `_RedisStyleBroker` Protocols,
in `src/protean/server/observatory/sse.py` and
`src/protean/server/subscription_status.py`, type the probed broker. #2069
replaces each probe with `broker.get_connection()` narrowed with
`isinstance(conn, redis.Redis)`, and deletes both Protocols.

`object` replaces `Any` on providers, keeps `object` on caches, and replaces
`MessageDBStore.client`, the `redis_instance` probes and both
`_RedisStyleBroker` types. `Any` would let a caller use the handle without
narrowing it, and mypy would not report it.

### 15. `trim` is its own sub-protocol behind `STREAM_RETENTION`

`BrokerCapabilities` gains `STREAM_RETENTION`, which unlocks
`StreamRetentionPort.trim`. `ENTERPRISE_STREAMING` gains the flag.
`RedisBroker` declares it. `InlineBroker` and `RedisPubSubBroker` do not, and
the `InlineBroker.trim` method is deleted.

Retention is independent of partitioning. `InlineBroker` supports neither, and
a log-based broker can keep a bounded stream without partitions. Folding `trim`
into `PartitioningPort` would force an adapter that only trims to write the
lease members. A no-op default on `BrokerPort` would hide a retention limit
that the adapter ignores. With its own flag, `StreamSubscription` logs one
start-up warning when a subscription sets `retention_maxlen` explicitly on a
broker without `STREAM_RETENTION`, and the `Broker` service's `trim` returns
0. A `retention_maxlen` that comes from a subscription profile's default logs
nothing (#2072).

### 16. Capability checks read the flag directly

A check is written `EventStoreCapabilities.EXPECTED_VERSION in
adapter.capabilities`. The `has_capability`, `has_all_capabilities` and
`has_any_capability` helpers on brokers and providers are removed.

Event stores and caches get full capability flags, each set following
`BrokerCapabilities`: individual flags, then named tiers. A flag counts only if
a test checks it. Each flag gates at least one conformance test, and the suite
fails when an adapter declares a flag and fails that flag's tests. The flags
and tiers are under [Capability flags](#capability-flags) below.

### 17. Conformance suites live in `tests/conformance/<port>/`

The suites stay in the repository and are not in the wheel.
`protean test test-adapter --port <port>` runs them from a source checkout, as
the command works today. `protean.testing` stays a single module, and
`tests/adapters/*/generic/` moves to `tests/conformance/`.

### 18. The port break ships without deprecation shims

`docs/reference/stable-surface.md` lists `BaseProvider`, `BaseBroker`,
`BaseEventStore`, `BaseCache` and the broker partition contract as
Provisional, so they may change in a minor release with a changelog notice.
The page does not name `BaseDAO` or `BaseLookup`. A provider's author
subclasses both to write the provider, so this decision treats them as part
of the Provisional provider port.

`domain.event_store.store`, which
`docs/reference/adapters/eventstore/index.md` and
`docs/patterns/temporal-queries.md` document, becomes
`domain.event_store.adapter`. #2058 keeps `.store` returning the same object
until #2062 removes it. Each sub-issue that renames
or removes a method a caller can reach adds its row to
`docs/reference/migration/v0-19.md` and a `.changed.md` or `.removed.md`
fragment in the same pull request.

Names that `docs/reference/stable-surface.md` lists as Stable keep working
with a `DeprecationWarning` that names their removal in 0.20.0:
`protean.testing.get_generic_test_dir()`, the `adapter_conformance` plugin's
`--db`, `--db-provider`, `--db-uri` and `--db-extra` options, and the
`protean test test-adapter` flags that change.

### 19. Four conflicts between sub-issues wait for a ruling

The sub-issues disagree in three places, and one member has no deciding
sub-issue. Each needs the maintainer's ruling before the sub-issue that
implements it starts. Where a conflict touches a table row, the row copies the
sub-issue in its "Decided in" column.

1. **The value type of `SUB_PROTOCOLS`.** #2070 types the broker table
   `dict[BrokerCapabilities, type[BrokerPort]]`. Every value is a Protocol
   with abstract methods, and mypy in strict mode rejects an abstract class
   where `type[BrokerPort]` is expected (`type-abstract`). The project allows
   no ignore comment, so the table needs another value type.
2. **The type of a database model class.** `model_for` returns
   `type[DatabaseModelPort]` (#2078), while `dao_for` takes
   `model_cls: type[BaseDatabaseModel]` (#2076). The repository in
   `src/protean/core/repository.py` passes the first into the second, which
   mypy in strict mode rejects. `DAOPort.database_model_cls` is
   `type[DatabaseModelPort]` (#2078, #2080), and
   `LookupPort.database_model_cls` is `type[BaseDatabaseModel] | None`
   (#2077). These four places give one concept two types.
3. **The arguments of `claim_lock`.** #2079 decides
   `claim_lock() -> AbstractContextManager[object]` and says #2080 keeps the
   same signature. #2080 says the same in its prose, and its sketch writes
   `claim_lock(self, session: SessionProtocol)`. The `DAOPort` table follows
   the #2080 sketch.
4. **A home for `_reclaim_idle_pending`.** `BaseBroker._reclaim_idle_pending(stream,
   group_name, consumer_name, min_idle_ms) -> dict[str, int]` in
   `src/protean/port/broker.py` has no Port member. `RedisBroker` overrides
   it, and `src/protean/server/subscription/broker_subscription.py` and
   `src/protean/server/subscription/stream_subscription.py` call it. It was
   added after the broker sub-issues were written, so none of them names it.
   Its default claims nothing and returns `{}`. Before `BaseBroker` is
   removed, it needs a Port member name, and a choice between a no-op default
   on `BrokerPort` and a sub-protocol behind a flag. The broker tables do not
   list it.

### Name tables

The tables show each Port after all port sub-issues land, with two limits
from Section 19: rows touched by conflicts 2 and 3 follow the sub-issue in
their "Decided in" column, and the broker tables leave out
`_reclaim_idle_pending` (conflict 4). Where a later
sub-issue narrows a type that an earlier one set, the table gives the final
type, and "Decided in" names every sub-issue that shaped the row.

"Replaces" names the member whose work the new member takes over, and a source
file at HEAD that defines it. `new` means the member has no predecessor. A row
marked "attribute" replaces an attribute or class attribute, not a method.
A method without a body in the Signature column is abstract. A member whose
signature ends in `: return <value>` is a no-op default. `__init__` and the
attribute rows follow neither rule: `__init__` is not abstract, and an
attribute has no body.

#### EventStorePort

Copied from #2056, with the flags from #2055.

| Member | Signature | Replaces | Decided in |
|--------|-----------|----------|------------|
| `name` | `name: str` | attribute `name` in `src/protean/port/event_store.py` | #2056 |
| `__init__` | `__init__(self, name: str, domain: Domain, config: Mapping[str, Any]) -> None` | `__init__` in `src/protean/port/event_store.py` | #2056 |
| `capabilities` | `@property capabilities(self) -> EventStoreCapabilities` | new | #2055, #2056 |
| `write_message` | <code>write&#95;message(self, stream&#95;name: str, message&#95;type: str, data: Mapping[str, Any], metadata: Mapping[str, Any] &#124; None = None, expected&#95;version: int &#124; None = None) -&gt; int</code> | `_write` in `src/protean/port/event_store.py` | #2056 |
| `get_stream_messages` | `get_stream_messages(self, stream_name: str, position: int = 0, limit: int = 1000) -> list[RawMessage]` | `_read` in `src/protean/port/event_store.py` | #2056 |
| `get_category_messages` | <code>get&#95;category&#95;messages(self, category: str, position: int = 0, limit: int = 1000, &#42;, consumer&#95;group&#95;member: int &#124; None = None, consumer&#95;group&#95;size: int &#124; None = None) -&gt; list[RawMessage]</code> | `_read` in `src/protean/port/event_store.py` | #2056 |
| `get_all_messages` | `get_all_messages(self, position: int = 0, limit: int = 1000) -> list[RawMessage]` | `_read` in `src/protean/port/event_store.py` | #2056 |
| `get_last_stream_message` | <code>get&#95;last&#95;stream&#95;message(self, stream&#95;name: str) -&gt; RawMessage &#124; None</code> | `_read_last_message` in `src/protean/port/event_store.py` | #2056 |
| `get_last_category_message` | <code>get&#95;last&#95;category&#95;message(self, category: str) -&gt; RawMessage &#124; None</code> | `_read_last_message` in `src/protean/port/event_store.py` | #2056 |
| `get_last_message` | <code>get&#95;last&#95;message(self) -&gt; RawMessage &#124; None</code> | `_read_last_message` in `src/protean/port/event_store.py` | #2056 |
| `stream_ids` | `stream_ids(self, category: str) -> list[str]` | `_stream_identifiers` in `src/protean/port/event_store.py` | #2056 |
| `ping` | `ping(self) -> bool` | new | #2056 |
| `health` | `health(self) -> EventStoreHealth` | new | #2056 |
| `get_connection` | `get_connection(self) -> object` | `client` in `src/protean/adapters/event_store/message_db.py` | #2056 |
| `clear` | `clear(self) -> None` | `_data_reset` in `src/protean/port/event_store.py` | #2056 |
| `close` | `close(self) -> None: return None` | `close` in `src/protean/port/event_store.py` | #2056 |
| `create_schema` | `create_schema(self) -> None: return None` | new | #2056 |
| `drop_schema` | `drop_schema(self) -> None: return None` | new | #2056 |

`config: Mapping[str, Any]`, set by the constructor, replaces the attribute
`conn_info`. `MessageDBStore.client` is a property today, so the row above
names it as a method. `_stream_head_position` is removed: the service computes
a category's head position from `get_last_category_message`. Both event
store adapters take the name `"default"`, because a domain has one event
store.

#### BrokerPort

Copied from #2069.

| Member | Signature | Replaces | Decided in |
|--------|-----------|----------|------------|
| `name` | `name: str` | attribute `name` in `src/protean/port/broker.py` | #2069 |
| `domain` | `domain: Domain` | attribute `domain` in `src/protean/port/broker.py` | #2069 |
| `config` | `config: Mapping[str, Any]` | attribute `conn_info` in `src/protean/port/broker.py` | #2069 |
| `__init__` | `__init__(self, name: str, domain: Domain, config: Mapping[str, Any]) -> None` | `__init__` in `src/protean/port/broker.py` | #2069 |
| `capabilities` | `@property capabilities(self) -> BrokerCapabilities` | `capabilities` in `src/protean/port/broker.py` | #2069 |
| `ping` | `ping(self) -> bool` | `_ping` in `src/protean/port/broker.py` | #2069 |
| `health` | `health(self) -> BrokerHealth` | `_health_stats` in `src/protean/port/broker.py` | #2069 |
| `get_connection` | `get_connection(self) -> object` | attribute `redis_instance` in `src/protean/adapters/broker/redis.py` | #2069 |
| `close` | `close(self) -> None: return None` | `close` in `src/protean/adapters/broker/redis.py` | #2069 |
| `clear` | `clear(self) -> None` | `_data_reset` in `src/protean/port/broker.py` | #2069 |
| `reconnect` | `reconnect(self) -> bool` | `_ensure_connection` in `src/protean/port/broker.py` | #2069 |
| `publish` | `publish(self, stream: str, message: dict[str, Any]) -> str` | `_publish` in `src/protean/port/broker.py` | #2069 |
| `read` | `read(self, stream: str, consumer_group: str, limit: int, *, new_messages: bool = False) -> list[BrokerMessage]` | `_read` in `src/protean/port/broker.py` | #2069 |
| `ack` | `ack(self, stream: str, message_id: str, consumer_group: str) -> bool` | `_ack` in `src/protean/port/broker.py` | #2069 |
| `nack` | `nack(self, stream: str, message_id: str, consumer_group: str) -> bool` | `_nack` in `src/protean/port/broker.py` | #2069 |
| `create_group` | `create_group(self, stream: str, consumer_group: str) -> None` | `_ensure_group` in `src/protean/port/broker.py` | #2069 |
| `consumer_groups` | `consumer_groups(self) -> dict[str, ConsumerGroupInfo]` | `_info` in `src/protean/port/broker.py` | #2069 |
| `mark_subscription_owned` | `mark_subscription_owned(self, stream: str, consumer_group: str) -> None: return None` | `_mark_subscription_owned` in `src/protean/port/broker.py` | #2069 |
| `remove_stale_consumers` | `remove_stale_consumers(self, stream: str, consumer_group: str, current_consumer: str) -> int: return 0` | `_cleanup_stale_consumers` in `src/protean/port/broker.py` | #2069 |

`read` also replaces `_get_next`, which the `Broker` service rebuilds as
`get_next`. The caller-facing names change with the adapter names:
`health_stats` becomes `health`, `info` becomes `consumer_groups` and
`ensure_connection` becomes `reconnect`.

#### BlockingReadPort

Copied from #2070. Unlocked by `BLOCKING_READ`.

| Member | Signature | Replaces | Decided in |
|--------|-----------|----------|------------|
| `read_blocking` | `read_blocking(self, stream: str, consumer_group: str, consumer_name: str, timeout_ms: int = 5000, limit: int = 1) -> list[BrokerMessage]` | `_read_blocking` in `src/protean/port/broker.py` | #2070 |
| `read_blocking_streams` | `read_blocking_streams(self, streams: Sequence[str], consumer_group: str, consumer_name: str, timeout_ms: int = 5000, limit: int = 1) -> dict[str, list[BrokerMessage]]` | `_read_blocking_streams` in `src/protean/port/broker.py` | #2070 |

#### DeadLetterQueuePort

Copied from #2071. Unlocked by `DEAD_LETTER_QUEUE`.

| Member | Signature | Replaces | Decided in |
|--------|-----------|----------|------------|
| `dlq_list` | `dlq_list(self, dlq_streams: list[str], limit: int = 100) -> list[DLQEntry]` | `_dlq_list` in `src/protean/port/broker.py` | #2071 |
| `dlq_get` | <code>dlq&#95;get(self, dlq&#95;stream: str, dlq&#95;id: str) -&gt; DLQEntry &#124; None</code> | `_dlq_inspect` in `src/protean/port/broker.py` | #2071 |
| `dlq_replay` | `dlq_replay(self, dlq_stream: str, dlq_id: str, target_stream: str) -> bool` | `_dlq_replay` in `src/protean/port/broker.py` | #2071 |
| `dlq_replay_all` | `dlq_replay_all(self, dlq_stream: str, target_stream: str) -> int` | `_dlq_replay_all` in `src/protean/port/broker.py` | #2071 |
| `dlq_purge` | `dlq_purge(self, dlq_stream: str) -> int` | `_dlq_purge` in `src/protean/port/broker.py` | #2071 |
| `dlq_trim` | `dlq_trim(self, dlq_stream: str, older_than: datetime) -> int` | `dlq_trim` in `src/protean/port/broker.py` | #2071 |
| `dlq_depth` | `dlq_depth(self, dlq_stream: str) -> int` | `dlq_depth` in `src/protean/port/broker.py` | #2071 |

#### PartitioningPort

Copied from #2072. Unlocked by `STREAM_PARTITIONING`.

| Member | Signature | Replaces | Decided in |
|--------|-----------|----------|------------|
| `record_partition` | `record_partition(self, category: str, key: str) -> None` | `_record_partition` in `src/protean/port/broker.py` | #2072 |
| `partition_keys` | `partition_keys(self, category: str) -> set[str]` | `_partition_keys` in `src/protean/port/broker.py` | #2072 |
| `reap_partition` | <code>reap&#95;partition(self, category: str, key: str, min&#95;idle&#95;ms: int, backfill&#95;suffix: str &#124; None) -&gt; bool</code> | `_reap_partition` in `src/protean/port/broker.py` | #2072 |
| `acquire_partition_lease` | <code>acquire&#95;partition&#95;lease(self, lease&#95;key: str, generation&#95;key: str, owner&#95;id: str, ttl&#95;ms: int) -&gt; int &#124; None</code> | `_acquire_partition_lease` in `src/protean/port/broker.py` | #2072 |
| `renew_partition_lease` | `renew_partition_lease(self, lease_key: str, fence_token: str, ttl_ms: int) -> bool` | `_renew_partition_lease` in `src/protean/port/broker.py` | #2072 |
| `release_partition_lease` | `release_partition_lease(self, lease_key: str, fence_token: str) -> bool` | `_release_partition_lease` in `src/protean/port/broker.py` | #2072 |
| `read_partition_fenced` | `read_partition_fenced(self, stream: str, consumer_group: str, consumer_name: str, lease_key: str, fence_token: str, limit: int, new_messages: bool) -> list[BrokerMessage]` | `_read_partition_fenced` in `src/protean/port/broker.py` | #2072 |
| `ack_partition_fenced` | `ack_partition_fenced(self, stream: str, message_id: str, consumer_group: str, lease_key: str, fence_token: str) -> bool` | `_ack_partition_fenced` in `src/protean/port/broker.py` | #2072 |
| `reclaim_partition_pending` | `reclaim_partition_pending(self, stream: str, consumer_group: str, consumer_name: str, min_idle_ms: int, limit: int) -> list[BrokerMessage]` | `_reclaim_partition_pending` in `src/protean/port/broker.py` | #2072 |

#### StreamRetentionPort

Copied from #2072. Unlocked by `STREAM_RETENTION`.

| Member | Signature | Replaces | Decided in |
|--------|-----------|----------|------------|
| `trim` | `trim(self, stream: str, maxlen: int) -> int` | `trim` in `src/protean/port/broker.py` | #2072 |

#### CachePort

Copied from #2066, with the flags from #2065.

| Member | Signature | Replaces | Decided in |
|--------|-----------|----------|------------|
| `name` | `name: str` | attribute `name` in `src/protean/port/cache.py` | #2066 |
| `domain` | `domain: Domain` | attribute `domain` in `src/protean/port/cache.py` | #2066 |
| `config` | `config: Mapping[str, Any]` | attribute `conn_info` in `src/protean/port/cache.py` | #2066 |
| `__init__` | `__init__(self, name: str, domain: Domain, config: Mapping[str, Any]) -> None` | `__init__` in `src/protean/port/cache.py` | #2066 |
| `capabilities` | `@property capabilities(self) -> CacheCapabilities` | new | #2065, #2066 |
| `ping` | `ping(self) -> bool` | `ping` in `src/protean/port/cache.py` | #2066 |
| `health` | `health(self) -> CacheHealth` | new | #2066 |
| `get_connection` | `get_connection(self) -> object` | `get_connection` in `src/protean/port/cache.py` | #2066 |
| `close` | `close(self) -> None: return None` | `close` in `src/protean/port/cache.py` | #2066 |
| `clear` | `clear(self) -> None` | `flush_all` in `src/protean/port/cache.py` | #2066 |
| `get` | <code>get(self, key: str) -&gt; CacheEntry &#124; None</code> | `get` in `src/protean/port/cache.py` | #2066 |
| `put` | <code>put(self, key: str, value: CacheEntry, ttl: float &#124; None) -&gt; None</code> | `add` in `src/protean/port/cache.py` | #2066 |
| `delete` | `delete(self, key: str) -> None` | `remove_by_key` in `src/protean/port/cache.py` | #2066 |

The adapter members store JSON-ready dicts under string keys. The `Cache`
service builds the keys and turns projections into dicts and back, and keeps
the caller-facing names, such as `add` and `remove_by_key`.

#### CacheTTLPort

Copied from #2066. Unlocked by `TTL`.

| Member | Signature | Replaces | Decided in |
|--------|-----------|----------|------------|
| `set_ttl` | `set_ttl(self, key: str, ttl: float) -> None` | `set_ttl` in `src/protean/port/cache.py` | #2066 |
| `get_ttl` | <code>get&#95;ttl(self, key: str) -&gt; float &#124; None</code> | `get_ttl` in `src/protean/port/cache.py` | #2066 |

#### CachePatternPort

Copied from #2066. Unlocked by `PATTERN_MATCH`.

| Member | Signature | Replaces | Decided in |
|--------|-----------|----------|------------|
| `keys_matching` | `keys_matching(self, pattern: str) -> list[str]` | `_get_all` in `src/protean/port/cache.py` | #2066 |
| `count_matching` | `count_matching(self, pattern: str) -> int` | `count` in `src/protean/port/cache.py` | #2066 |
| `delete_matching` | `delete_matching(self, pattern: str) -> None` | `remove_by_key_pattern` in `src/protean/port/cache.py` | #2066 |

`keys_matching` returns distinct keys in ascending order. It takes over the
key scan inside `_get_all`, and the `Cache` service reads each key with
`get`.

#### ProviderPort

Copied from #2076, with members added or narrowed by #2077, #2078 and #2080.

| Member | Signature | Replaces | Decided in |
|--------|-----------|----------|------------|
| `database_type` | `database_type: ClassVar[str]` | attribute `__database__` in `src/protean/port/provider.py` | #2076 |
| `name` | `name: str` | attribute `name` in `src/protean/port/provider.py` | #2076 |
| `domain` | `domain: Domain` | attribute `domain` in `src/protean/port/provider.py` | #2076 |
| `config` | `config: Mapping[str, Any]` | attribute `conn_info` in `src/protean/port/provider.py` | #2076 |
| `__init__` | `__init__(self, name: str, domain: Domain, config: Mapping[str, Any]) -> None` | `__init__` in `src/protean/port/provider.py` | #2076 |
| `capabilities` | `@property capabilities(self) -> DatabaseCapabilities` | `capabilities` in `src/protean/port/provider.py` | #2076 |
| `get_session` | `get_session(self) -> SessionProtocol` | `get_session` in `src/protean/port/provider.py` | #2076 |
| `get_connection` | `get_connection(self) -> object` | `get_connection` in `src/protean/port/provider.py` | #2076 |
| `ping` | `ping(self) -> bool` | `is_alive` in `src/protean/port/provider.py` | #2076 |
| `health` | `health(self) -> ProviderHealth` | `pool_stats` in `src/protean/port/provider.py` | #2076 |
| `close` | `close(self) -> None` | `close` in `src/protean/port/provider.py` | #2076 |
| `clear` | `clear(self) -> None` | `_data_reset` in `src/protean/port/provider.py` | #2076 |
| `create_schema` | `create_schema(self) -> None: return None` | `_create_database_artifacts` in `src/protean/port/provider.py` | #2076 |
| `drop_schema` | `drop_schema(self) -> None: return None` | `_drop_database_artifacts` in `src/protean/port/provider.py` | #2076 |
| `dao_for` | `dao_for(self, entity_cls: type[BaseEntity], model_cls: type[BaseDatabaseModel]) -> DAOPort` | `get_dao` in `src/protean/port/provider.py` | #2076, #2080 |
| `model_for` | <code>model&#95;for(self, entity&#95;cls: type[BaseEntity], model&#95;cls: type[BaseDatabaseModel] &#124; None = None) -&gt; type[DatabaseModelPort]</code> | `construct_database_model_class` and `decorate_database_model_class` in `src/protean/port/provider.py` | #2076, #2078 |
| `get_lookup` | `get_lookup(self, lookup_name: str) -> type[LookupPort]` | `get_lookup` in `src/protean/utils/query.py` | #2076, #2077 |
| `get_lookups` | `@classmethod get_lookups(cls) -> Mapping[str, type[LookupPort]]` | `get_lookups` in `src/protean/utils/query.py` | #2077 |
| `new_session` | `new_session(self) -> SessionProtocol` | `_get_session` in `src/protean/adapters/repository/sqlalchemy.py` | #2080 |
| `commit` | `commit(self, session: SessionProtocol) -> None` | `_commit_if_standalone` in `src/protean/port/dao.py` | #2080 |
| `rollback` | `rollback(self, session: SessionProtocol) -> None` | `_rollback_if_standalone` in `src/protean/port/dao.py` | #2080 |
| `flush` | `flush(self, session: SessionProtocol) -> None: return None` | `_flush` in `src/protean/adapters/repository/sqlalchemy.py` | #2080 |

`close` is abstract on `ProviderPort`, while the event-store, broker and cache
Ports give it a no-op default. `managed` is framework state: the `Provider`
service reads it, and `ProviderPort` does not list it. #2080 writes
`commit(session)`, `rollback(session)` and `flush(session)` without a type, and
the table types `session` as `SessionProtocol`, the type `new_session()`
returns. `SessionProtocol` loses its optional `begin()` note, because
`get_session()` returns a session that has already begun (#2083).

#### RawQueryProviderPort

Copied from #2076. Unlocked by `RAW_QUERIES`.

| Member | Signature | Replaces | Decided in |
|--------|-----------|----------|------------|
| `raw` | `raw(self, query: Any, data: Any = None) -> Any` | `_raw` in `src/protean/port/provider.py` | #2076 |

#### DAOPort

Copied from #2080, with `claim_lock` from #2079.

| Member | Signature | Replaces | Decided in |
|--------|-----------|----------|------------|
| `provider` | `provider: ProviderPort` | attribute `provider` in `src/protean/port/dao.py` | #2080 |
| `entity_cls` | `entity_cls: type[BaseEntity]` | attribute `entity_cls` in `src/protean/port/dao.py` | #2080 |
| `database_model_cls` | `database_model_cls: type[DatabaseModelPort]` | attribute `database_model_cls` in `src/protean/port/dao.py` | #2078, #2080 |
| `schema_name` | `schema_name: str` | attribute `schema_name` in `src/protean/port/dao.py` | #2080 |
| `filter` | <code>filter(self, session: SessionProtocol, criteria: Q, &#42;, offset: int = 0, limit: int = 10, order&#95;by: Sequence[str] = (), with&#95;total: bool = True, fields: Sequence[str] &#124; None = None) -&gt; ResultSet</code> | `_filter` in `src/protean/port/dao.py` | #2080 |
| `count` | `count(self, session: SessionProtocol, criteria: Q) -> int` | `_count` in `src/protean/port/dao.py` | #2080 |
| `insert` | `insert(self, session: SessionProtocol, model: Any) -> Any` | `_create` in `src/protean/port/dao.py` | #2080 |
| `update` | <code>update(self, session: SessionProtocol, model: Any, &#42;, expected&#95;version: int &#124; None = None) -&gt; Any</code> | `_update` in `src/protean/port/dao.py` | #2080 |
| `update_all` | `update_all(self, session: SessionProtocol, criteria: Q, values: Mapping[str, Any]) -> int` | `_update_all` in `src/protean/port/dao.py` | #2080 |
| `delete` | `delete(self, session: SessionProtocol, model: Any) -> Any` | `_delete` in `src/protean/port/dao.py` | #2080 |
| `delete_all` | <code>delete&#95;all(self, session: SessionProtocol, criteria: Q &#124; None = None) -&gt; int</code> | `_delete_all` in `src/protean/port/dao.py` | #2080 |
| `has_table` | `has_table(self) -> bool` | `has_table` in `src/protean/port/dao.py` | #2080 |
| `claim_lock` | `claim_lock(self, session: SessionProtocol) -> AbstractContextManager[object]: return nullcontext()` | new | #2079, #2080 |

After #2080, an adapter DAO is built as
`(provider, entity_cls, database_model_cls)`, without the `domain` argument
`BaseDAO` takes today.
`DAOPort` has no `flush` member: flushing acts on the session, which the
provider owns.

#### RawQueryDAOPort

Copied from #2080. Unlocked by `RAW_QUERIES`.

| Member | Signature | Replaces | Decided in |
|--------|-----------|----------|------------|
| `raw` | `raw(self, session: SessionProtocol, query: Any, data: Any = None) -> ResultSet` | `_raw` in `src/protean/port/dao.py` | #2080 |

#### NativeClaimPort

Copied from #2079, with the `session` argument from #2080. Unlocked by
`NATIVE_CLAIM`.

| Member | Signature | Replaces | Decided in |
|--------|-----------|----------|------------|
| `claim` | <code>claim(self, session: SessionProtocol, criteria: Q, claim&#95;fields: Mapping[str, Any], limit: int, order&#95;by: Sequence[str] = (), hold&#95;back: HoldBack &#124; None = None) -&gt; list[Any]</code> | `_claim` in `src/protean/port/dao.py` | #2079, #2080 |

#### ClaimCandidatesPort

Copied from #2079, with the `session` argument from #2080. Unlocked by
`FILTERED_CLAIM_CANDIDATES`.

| Member | Signature | Replaces | Decided in |
|--------|-----------|----------|------------|
| `claim_candidates` | `claim_candidates(self, session: SessionProtocol, criteria: Q, limit: int, offset: int, order_by: Sequence[str], hold_back: HoldBack) -> list[Any]` | `_claim_candidates` in `src/protean/port/dao.py` | #2079, #2080 |

#### BoundedDeletePort

Copied from #2079, with the `session` argument from #2080. Unlocked by
`BOUNDED_DELETE`.

| Member | Signature | Replaces | Decided in |
|--------|-----------|----------|------------|
| `delete_top` | <code>delete&#95;top(self, session: SessionProtocol, criteria: Q, limit: int, order&#95;by: str &#124; None = None) -&gt; int</code> | `_delete_top` in `src/protean/port/dao.py` | #2079, #2080 |

The `DAO` service keeps `portable_claim` and `portable_delete_top` as
module functions for adapters without these flags.

#### InsertIfAbsentPort

Copied from #2080. Unlocked by `INSERT_IF_ABSENT`.

| Member | Signature | Replaces | Decided in |
|--------|-----------|----------|------------|
| `insert_if_absent` | `insert_if_absent(self, session: SessionProtocol, model: Any) -> bool` | `save_if_absent` in `src/protean/adapters/repository/memory.py` and `src/protean/adapters/repository/sqlalchemy.py` | #2080 |
| `update_if_absent` | <code>update&#95;if&#95;absent(self, session: SessionProtocol, model: Any, &#42;, expected&#95;version: int &#124; None = None) -&gt; bool</code> | `save_if_absent` in `src/protean/adapters/repository/memory.py` and `src/protean/adapters/repository/sqlalchemy.py` | #2080 |

Each member writes `model` only when no other stored row holds one of its
unique keys, in one atomic step, and returns `False` without writing
otherwise. `DictDAO` and `SADAO` each implement both members.

#### LookupPort

Copied from #2077.

| Member | Signature | Replaces | Decided in |
|--------|-----------|----------|------------|
| `lookup_name` | `lookup_name: ClassVar[str]` | attribute `lookup_name` in `src/protean/port/dao.py` | #2077 |
| `source` | `source: Any` | attribute `source` in `src/protean/port/dao.py` | #2077 |
| `target` | `target: Any` | attribute `target` in `src/protean/port/dao.py` | #2077 |
| `database_model_cls` | <code>database&#95;model&#95;cls: type[BaseDatabaseModel] &#124; None</code> | attribute `database_model_cls` in `src/protean/port/dao.py` | #2077 |
| `__init__` | <code>&#95;&#95;init&#95;&#95;(self, source: Any, target: Any, &#42;, database&#95;model&#95;cls: type[BaseDatabaseModel] &#124; None = None) -&gt; None</code> | `__init__` in `src/protean/port/dao.py` | #2077 |

`LookupPort` and `REQUIRED_LOOKUPS`, now a module-level constant, live in
`src/protean/port/dao.py`. `split_lookup_key(key: str) -> tuple[str, str]` in
`protean.utils.query` splits a filter key into the field name and the lookup
name, defaulting to `"exact"`. A lookup class is checked with
`LookupPort in lookup.__mro__`.

#### DatabaseModelPort

Copied from #2078.

| Member | Signature | Replaces | Decided in |
|--------|-----------|----------|------------|
| `from_entity` | `@classmethod from_entity(cls, entity: BaseEntity) -> Any` | `from_entity` in `src/protean/core/database_model.py` | #2078 |
| `to_entity` | `@classmethod to_entity(cls, item: Any) -> BaseEntity` | `to_entity` in `src/protean/core/database_model.py` | #2078 |
| `to_records` | `@classmethod to_records(cls, items: list[Any], fields: list[str]) -> list[Record]` | `to_records` in `src/protean/core/database_model.py` | #2078 |

`DatabaseModelPort` lives in `src/protean/port/provider.py`.
`BaseDatabaseModel` stays as the base class for model classes, and each model
module checks its class with `_MODEL_PORT_CHECK`.

### Typed records

`RawMessage`, a `TypedDict` in the event-store port (#2056):

```python
class RawMessage(TypedDict):
    id: str
    stream_name: str
    type: str
    position: int
    global_position: int
    data: dict[str, Any] | None
    metadata: dict[str, Any] | None
    time: datetime
```

A snapshot row has `type` set to `"SNAPSHOT"` and `metadata` set to `None`.

The broker records (#2069, #2071):

```python
class BrokerMessage(NamedTuple):
    id: str
    payload: dict[str, Any]

class ConsumerInfo(TypedDict):
    name: str
    pending: int

class ConsumerGroupInfo(TypedDict):
    name: str
    consumer_count: int
    pending: int
    consumers: NotRequired[list[ConsumerInfo]]
    last_delivered_id: NotRequired[str]
    created_at: NotRequired[float]

@dataclass
class DLQEntry:
    dlq_id: str
    original_id: str
    stream: str
    consumer_group: str
    payload: dict[str, Any]
    failure_reason: str
    failed_at: str | None
    retry_count: int
    dlq_stream: str
```

`DLQEntry` exists today and keeps its fields. `LeaseLostError` stays in
`src/protean/port/broker.py`. `OperationState` moves to
`src/protean/adapters/broker/inline.py`, its only user (#2073).

The cache record (#2066):

```python
CacheEntry = dict[str, Any]
```

The health records:

```python
class PoolStats(TypedDict):
    size: int
    checked_out: int
    overflow: int
    checked_in: int

@dataclass
class EventStoreHealth:
    pool: PoolStats | None

@dataclass
class CacheHealth:
    pool: PoolStats | None

@dataclass
class ProviderHealth:
    pool: PoolStats | None
```

#2056 creates `PoolStats` in `src/protean/port/health.py`, and #2066 and #2076
import it from there.

`BrokerHealth` has one field per key that `InlineBroker`, `RedisBroker` and
`RedisPubSubBroker` return from `_health_stats` today, with each field named
after its key. A key that all three brokers return on every path is required.
Every other key is optional and defaults to `None`.

```python
@dataclass
class BrokerHealth:
    healthy: bool
    message_counts: dict[str, int]
    consumer_groups: dict[str, int | list[str]]
    configuration: dict[str, Any]
    streams: dict[str, int | list[str]] | None = None
    memory_estimate_bytes: int | None = None
    error: str | None = None
    warning: str | None = None
    hit_rate: float | None = None
    redis_version: str | None = None
    connected_clients: int | None = None
    used_memory: int | None = None
    used_memory_human: str | None = None
    used_memory_peak: int | None = None
    used_memory_peak_human: str | None = None
    keyspace_hits: int | None = None
    keyspace_misses: int | None = None
    expired_keys: int | None = None
    evicted_keys: int | None = None
    total_commands_processed: int | None = None
    instantaneous_ops_per_sec: int | None = None
    role: str | None = None
    uptime_in_seconds: int | None = None
    tcp_port: int | None = None
```

`message_counts` holds `total_messages`, `in_flight`, `failed` and `dlq` on the
inline and Redis brokers, and `total_messages` on the Redis Pub/Sub broker.
`consumer_groups` holds `count` and `names`, and `streams` holds `count` and
`names`. `configuration` keeps `dict[str, Any]` because its keys differ per
broker. `streams` and `memory_estimate_bytes` come from the inline and Redis
brokers. `error`, `warning` and `hit_rate` come from the Redis and Redis
Pub/Sub brokers. Of the Redis server fields, `connected_clients`,
`used_memory`, `used_memory_human`, `keyspace_hits` and `keyspace_misses` come
from both Redis brokers, and the other ten come from the Redis broker only.

### Capability flags

#### EventStoreCapabilities

Decided in #2055.

| Flag | Meaning |
|------|---------|
| `WRITE` | Appends a message and returns its stream position. |
| `READ_STREAM` | Reads one stream by stream position. |
| `READ_CATEGORY` | Reads a category by global position, inclusive, per ADR-0024. |
| `READ_ALL` | Reads the whole store by global position, inclusive. |
| `EXPECTED_VERSION` | A stale write raises `ExpectedVersionError` and writes nothing. |
| `CATEGORY_COMMIT_ORDER` | Writes to one category become visible in global-position order, which ADR-0025 relies on. |
| `CONSUMER_GROUPS` | A category read can be split across the members of a group. |
| `DURABLE` | Messages survive a process restart. |
| `SCHEMA_MANAGEMENT` | The store creates and drops its own tables. |

| Tier | Flags |
|------|-------|
| `BASIC_STORE` | `WRITE`, `READ_STREAM`, `READ_CATEGORY`, `READ_ALL` |
| `CONSISTENT_STORE` | `BASIC_STORE`, `EXPECTED_VERSION`, `CATEGORY_COMMIT_ORDER` |
| `PRODUCTION_STORE` | `CONSISTENT_STORE`, `DURABLE` |

The memory event store declares `CONSISTENT_STORE`. The Message DB store
declares `PRODUCTION_STORE | CONSUMER_GROUPS` once #2056 lands.

#### CacheCapabilities

Decided in #2065.

| Flag | Meaning |
|------|---------|
| `KEY_VALUE` | Gets, puts and deletes by key. |
| `TTL` | Expires each key after its own time to live. |
| `PATTERN_MATCH` | Reads, counts and deletes keys that match a glob pattern. |
| `SHARED` | A second adapter built from the same config sees the first one's writes. |
| `DURABLE` | Entries survive closing and reopening the adapter. |

| Tier | Flags |
|------|-------|
| `LOCAL` | `KEY_VALUE`, `TTL`, `PATTERN_MATCH` |
| `DISTRIBUTED` | `LOCAL`, `SHARED`, `DURABLE` |

`MemoryCache` declares `LOCAL`. `RedisCache` declares `DISTRIBUTED`.

#### BrokerCapabilities

The flags and tiers exist today in `src/protean/port/broker.py`. #2072 adds
`STREAM_RETENTION` and puts it in `ENTERPRISE_STREAMING`.

Flags: `PUBLISH`, `SUBSCRIBE`, `CONSUMER_GROUPS`, `ACK_NACK`,
`DELIVERY_GUARANTEES`, `MESSAGE_ORDERING`, `BLOCKING_READ`,
`DEAD_LETTER_QUEUE`, `REPLAY`, `STREAM_PARTITIONING`, `STREAM_RETENTION`.

| Tier | Flags |
|------|-------|
| `BASIC_PUBSUB` | `PUBLISH`, `SUBSCRIBE` |
| `SIMPLE_QUEUING` | `BASIC_PUBSUB`, `CONSUMER_GROUPS` |
| `RELIABLE_MESSAGING` | `SIMPLE_QUEUING`, `ACK_NACK`, `DELIVERY_GUARANTEES` |
| `ORDERED_MESSAGING` | `RELIABLE_MESSAGING`, `MESSAGE_ORDERING` |
| `ENTERPRISE_STREAMING` | `ORDERED_MESSAGING`, `DEAD_LETTER_QUEUE`, `REPLAY`, `STREAM_PARTITIONING`, `BLOCKING_READ`, `STREAM_RETENTION` |

`InlineBroker` declares `RELIABLE_MESSAGING | DEAD_LETTER_QUEUE`. #2071 gives
it `dlq_trim` and `dlq_depth`, which it lacks today, so it implements all of
`DeadLetterQueuePort`.
`RedisBroker` declares `ORDERED_MESSAGING | BLOCKING_READ | DEAD_LETTER_QUEUE
| STREAM_PARTITIONING`, and gains `STREAM_RETENTION`. `RedisPubSubBroker`
declares `SIMPLE_QUEUING`.

#### DatabaseCapabilities

The flags and tiers exist today in `src/protean/port/provider.py`. #2075 adds
`NATIVE_CLAIM`, `BOUNDED_DELETE` and `FILTERED_CLAIM_CANDIDATES`, and #2080
adds `INSERT_IF_ABSENT`. The tier names and their members do not change.

Flags: `CRUD`, `FILTER`, `BULK_OPERATIONS`, `ORDERING`, `TRANSACTIONS`,
`SIMULATED_TRANSACTIONS`, `OPTIMISTIC_LOCKING`, `RAW_QUERIES`,
`SCHEMA_MANAGEMENT`, `CONNECTION_POOLING`, `NATIVE_JSON`, `NATIVE_ARRAY`,
`NATIVE_CLAIM`, `BOUNDED_DELETE`, `FILTERED_CLAIM_CANDIDATES`,
`INSERT_IF_ABSENT`.

| Tier | Flags |
|------|-------|
| `BASIC_STORAGE` | `CRUD`, `FILTER`, `BULK_OPERATIONS`, `ORDERING` |
| `RELATIONAL` | `BASIC_STORAGE`, `TRANSACTIONS`, `OPTIMISTIC_LOCKING`, `RAW_QUERIES`, `SCHEMA_MANAGEMENT`, `CONNECTION_POOLING` |
| `DOCUMENT_STORE` | `BASIC_STORAGE`, `SCHEMA_MANAGEMENT`, `OPTIMISTIC_LOCKING` |
| `IN_MEMORY` | `BASIC_STORAGE`, `SIMULATED_TRANSACTIONS`, `OPTIMISTIC_LOCKING`, `RAW_QUERIES` |

Each provider declares the new flags as follows:

| Provider | `NATIVE_CLAIM` | `BOUNDED_DELETE` | `FILTERED_CLAIM_CANDIDATES` | `INSERT_IF_ABSENT` |
|----------|----------------|------------------|-----------------------------|--------------------|
| PostgreSQL | yes | yes | yes | yes |
| SQLite | no | yes | yes | yes |
| MSSQL | no | yes | yes | yes |
| MySQL | no | no | yes | yes |
| Memory | no | yes | no | yes |
| Elasticsearch | no | yes | no | no |

### Service method lists

Each service is the class a caller uses. Each list below is the one its
sub-issue decides.

**`EventStore`** in `src/protean/infra/event_store.py` (#2058, #2059). Its
`adapter` attribute is typed `EventStorePort | None`.

- `append(self, message_object: BaseEvent | BaseCommand) -> int`
- `read(self, stream: str, position: int = 0, limit: int = 1000) -> list[Message]`
- `read_all(self, stream: str = "$all", *, page_size: int = 1000) -> Iterator[Message]`
- `read_last_message(self, stream: str) -> Message | None`
- `category_head_position(self, category: str) -> int`
- `load_aggregate(self, part_of: type[BaseAggregate], identifier: str, *, at_version: int | None = None, as_of: datetime | None = None) -> BaseAggregate | None`
- `create_snapshot(self, part_of: type[BaseAggregate], identifier: str) -> bool`
- `create_snapshots(self, part_of: type[BaseAggregate]) -> int`
- `category(stream: str) -> str`, a static method
- `trace_causation`, `trace_effects`, `build_causation_tree` and `verify`,
  which call the module functions below
- `close()` and `_initialize()`, which stay on the service from the container

The `causation` module holds `CausationNode`, `trace_causation(adapter,
message_id)`, `trace_effects(adapter, message_id, *, recursive=True)`,
`build_causation_tree(adapter, correlation_id)`,
`load_correlation_group(adapter, correlation_id)` and
`build_tree_from_group(group)`. The `integrity` module holds
`IntegrityViolation`, `IntegrityReport`, `ViolationKind` and
`verify(adapter)`. `ViolationKind` is a `StrEnum` with the members
`DUPLICATE_MESSAGE_ID`, `POSITION_GAP`, `NON_MONOTONIC_GLOBAL_POSITION`,
`SNAPSHOT_AHEAD_OF_STREAM`, `MALFORMED_MESSAGE` and `MALFORMED_SNAPSHOT`.

**`Broker`** in `src/protean/infra/broker.py` (#2069 to #2073). It holds
empty-message validation, unit-of-work recording, the single retry after a
connection error, synchronous subscriber dispatch with `register` and the
subscriber map, capability checks before `get_next`, `read`, `ack` and `nack`,
ping timing, the health envelope, and pass-through methods for every core
member. `Broker.capabilities` returns the adapter's flags.

- `get_next(stream, consumer_group)` calls `read` with `limit=1` and
  `new_messages=True`.
- `read_blocking` and `read_blocking_streams` call `read` once per stream,
  with no wait, on an adapter without `BLOCKING_READ`, and retry once after a
  connection error.
- The seven `dlq_*` methods return the empty value without
  `DEAD_LETTER_QUEUE`. `dlq_trim` raises `ValueError` for a naive
  `older_than`.
- The partition methods do not retry, and raise `NotSupportedError` without
  `STREAM_PARTITIONING`. They default `reap_partition(backfill_suffix=None)`,
  `read_partition_fenced(limit=1, new_messages=True)` and
  `reclaim_partition_pending(min_idle_ms=0, limit=100)`.
- `trim` returns 0 without `STREAM_RETENTION`.

The module also holds `is_connection_error(exc)` and the `Brokers` container.

**`Cache`** in `src/protean/infra/cache.py` (#2066). It keeps the
caller-facing names `add`, `get`, `_get_all`, `count`, `remove`,
`remove_by_key`, `remove_by_key_pattern`, `set_ttl`, `get_ttl`, `ping`,
`get_connection`, `close` and `register_projection`, renames `flush_all` to
`clear`, and adds `capabilities`. `count`, `_get_all` and
`remove_by_key_pattern` raise `NotSupportedError` without `PATTERN_MATCH`, and
`set_ttl` and `get_ttl` raise it without `TTL`. Without `TTL`, `add` stores
an entry with no expiry, and `add(p, ttl=...)` with an explicit TTL raises
`NotSupportedError` naming the cache and `TTL`. `_resolve_ttl`, `_ttl_unset`,
`DEFAULT_TTL`, `TTLValue` and `GET_ALL_MAX` move into the service module, and
the module also holds the `Caches` container.

**`Provider`** in `src/protean/infra/provider.py` (#2085). It has `adapter:
ProviderPort`, `name: str`, `managed: bool` (read from `config["managed"]`,
default `True`), the `capabilities` property, `raw(query, data=None)`, which
raises `NotSupportedError` without `RAW_QUERIES`, and `owns(element_cls)`. The
module holds the function `owns(domain, provider_name, element_cls) -> bool`
and the `Providers` container. Code that needs a technology checks
`isinstance(provider.adapter, SAProvider)`.

**`DAO`** in `src/protean/infra/dao.py` (#2080 to #2083), built as
`DAO(domain, provider, adapter: DAOPort)`. It holds every method `BaseDAO` had
except the adapter operations, plus `session_scope()` and the
`INSERT_IF_ABSENT` dispatch in `save_if_absent`. The service's underscore
methods that framework code outside the service calls take public names:
`claim`, `delete_top`, `update_all` and `delete_all(criteria)`. `delete_all()`
with no criteria keeps its current meaning. Three modules split it:

- `dao_read` (#2081): `fetch(criteria, *, offset=0, limit=10, order_by=(),
  with_total=True, fields=None) -> ResultSet`, `count(criteria) -> int`,
  `raw(query, data=None) -> ResultSet`, `get`, `find_by` and `exists`.
- `dao_write` (#2082): `create`, `save`, `save_if_absent`, the deprecated
  `update`, `_apply_update`, `delete`, `delete_all`, and the public
  `apply_pre_persist_hooks` and `flush`.
- `dao_tracking` (#2083): the `is_standalone` property, `track(entity) ->
  BaseEntity` and `tracked_instance(entity) -> BaseAggregate | None`.
  `outside_uow()` returns a new service. The Unit of Work flushes, commits and
  rolls back through the provider's `flush`, `commit` and `rollback`.

## Consequences

- An adapter author implements one Protocol and the sub-protocols for the
  flags they declare. The Port lists every member they must write, and mypy
  reports a missing member at the module's `_PORT_CHECK` line.
- The registry and the service each reject an incomplete adapter with an error
  that names the missing members or the flag, at load time or when the service
  is built.
- Framework code calls services, so a feature such as retries or aggregate
  loading has one implementation and every adapter gets it.
- Every port declares capability flags, so a service can check what an
  adapter supports before it calls it. Each new event-store and cache flag
  gates conformance tests.
- Records crossing a Port have types, so mypy checks the keys and fields that
  callers read.
- The break is large. Every adapter, container and fixture changes, and code
  that subclasses a `Base*` class or calls an underscore method must move to
  the new names. The migration guide for 0.19 lists each change. Stable
  testing names keep working with a warning until 0.20.0.
- Outside adapters register through entry points, through the same registry
  as the built-in adapters.
- `get_connection()` returns `object`, so a caller that uses the handle must
  narrow it first.
- `protean.adapters` holds only implementations, so the `protean check`
  diagnostic on `protean.adapters` imports keeps flagging infrastructure
  imports from domain code.

## Alternatives Considered

**Keep abstract base classes and trim them.** If the Port kept features such
as `load_aggregate` or `verify`, every adapter would have to implement or
inherit them, and an inherited base class would come back under another name.
A Protocol holds no logic, and the service holds the features once.

**Use `runtime_checkable` Protocols with `isinstance` checks.** A runtime
check sees method names only, so a member with the wrong signature passes.
Explicit subclassing with `@abstractmethod` makes Python refuse an incomplete
adapter. Mypy reports a method with the wrong signature at the class
definition, and a missing method at the typed assignment. Mypy does not
compare an adapter's `__init__` with the Port's.

**Put the services in `protean.services`.** "Service" already names domain
services and application services in Protean, so the package name would
confuse readers.

**Put each service in `protean/adapters/<port>/__init__.py`.** That package
would then mix the framework with the adapters it wraps, and the `protean
check` diagnostic on `protean.adapters` imports would flag framework imports.

**Give `BrokerPort` a no-op `trim`, or fold it into `PartitioningPort`.** A
no-op would hide a retention limit the adapter ignores. Folding it into
`PartitioningPort` would force an adapter that only trims to write the lease
members.

**Type `get_connection()` as `Any`.** `Any` lets a caller use the handle
without narrowing it, and mypy would not report a wrong assumption about its
type.

**Keep deprecation shims for the renamed port methods.** The port base classes
and the partition contract are Provisional, so the stable-surface policy lets
them change in a minor release with a changelog notice. The migration guide
gives each caller the new name. Stable names outside the ports keep the
deprecation period.
