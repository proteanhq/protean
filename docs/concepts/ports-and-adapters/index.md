# Ports & Adapters Architecture

A core principle of Protean is to keep the domain separate from the underlying
infrastructure. You can write and test your models before you choose any
technology. When you are ready, you add the component for the technology you
chose. This lets you delay your decision on technology until [the last
responsible
moment](https://blog.codinghorror.com/the-last-responsible-moment/), the latest
point at which you can still decide without closing off options.

Protean's design is based on the [Ports and Adapters architecture](https://en.wikipedia.org/wiki/Hexagonal_architecture_(software)),
also known as Hexagonal Architecture,
allowing loosely coupled components that can be easily connected and swapped.

**Ports** are abstract interfaces that define a specific type of interaction
between the application and the outside world. They define a protocol that can
be implemented by concrete technology implementations called adapters.

**Adapters** connect the application to the outside world. Each adapter
translates the exchanges between an external technology and a port. The port
states what the application requires from that technology.

Protean exposes several ports with an array of built-in adapters for
each port.

## In-Memory Adapters

Every port ships with a **complete in-memory implementation** that is active by
default. These are not stubs or mocks. They implement the full provider
interface (CRUD, filtering, sorting, stream reads, consumer groups, data reset)
using Python data structures instead of external services. This means you can
develop and test your entire domain model without any infrastructure running.

Memory adapters and real adapters share the same interface, so you can run the
**same test suite** in both modes. Use in-memory mode for fast feedback during
development, and real infrastructure for final validation. Switch with a single
flag: `pytest --protean-env memory`. See [Dual-Mode
Testing](../../patterns/dual-mode-testing.md) for the full pattern.

| Port | In-Memory Adapter | Default |
|------|-------------------|---------|
| Database | `memory` | Yes |
| Broker | `inline` | Yes |
| Event Store | `memory` | Yes |
| Cache | `memory` | Yes |

## Database Adapter Architecture

A database adapter has four components that work together to make database
communication possible. Each adapter will override the corresponding base
classes for each of these components with its own implementation.

!!!note
    An exception to this rule is the `Session` class. It may be preferable to
    use the `Session` structures provided by the database technology as-is. For
    example, `PostgreSQL` adapter that is powered by `SQLAlchemy` uses
    (and returns) the [sqlalchemy.orm.Session](https://docs.sqlalchemy.org/en/20/orm/session_api.html#sqlalchemy.orm.Session)
    object provided by `SQLAlchemy`.

### Provider

**Base Class**: `protean.port.provider.BaseProvider`

The Provider is the main component responsible for interfacing with the
specific database technology. It contains the configuration and setup needed to
connect to the database. It also provides high-level methods for database
operations.

The Provider connects the application to the database: it opens the connections
the application needs and keeps them open. It also implements the behavior
specific to each database, such as connection pooling, transaction management,
and query optimization.

To add a new provider, subclass from the Provider Base class. Then implement
its methods for your database technology.

### Data Access Object (DAO)

**Base Class**: `protean.port.dao.BaseDAO`

The Data Access Object (DAO) is responsible for encapsulating the details of
the database interactions. It provides an abstract interface to the database,
hiding the complexity of the underlying database operations from the rest of
the application.

The DAO defines methods for CRUD (Create, Read, Update, Delete) operations
and other database queries, translating them into the appropriate SQL or
database-specific commands.

By using DAOs, the application code remains clean and decoupled from the
database logic. DAOs and [lookups](#lookups) together provide a query API that
works across various adapters.

To add a new DAO for your provider, subclass from the DAO Base class. Then
implement its methods for your database technology.

### Session

The Session component opens, commits and closes database transactions. It is
responsible for opening and closing connections, beginning and committing
transactions, and ensuring data consistency.

The Session provides a context for database operations. Within a transaction,
the Session groups every database operation and releases its resources when the
transaction ends. The Session keeps each transaction intact and rolls the
transaction back when an error occurs.

The Session object is usually constructed and provided by the database orm
or technology package. For example, `PostgreSQL` adapter depends on the
[sqlalchemy.orm.Session](https://docs.sqlalchemy.org/en/20/orm/session_api.html#sqlalchemy.orm.Session)
object provided by `SQLAlchemy`.

### Model

**Base Class**: `protean.core.database_model.BaseDatabaseModel`

The Model represents the domain entities that are persisted in the database. It
defines the structure of the data, including fields, relationships, and
constraints. It is also a high-level abstraction over database records. You
read and change the data through Python objects, without writing raw queries.

Models are typically defined using a schema or an ORM
(Object-Relational Mapping) framework that maps the database tables to
Python objects.

You may find it slightly involved to implement a model for your database
technology, because ORM packages can depend heavily on their internal
structures. Every database package is structured differently. Consult existing
models for PostgreSQL
([SQLAlchemy](https://github.com/proteanhq/protean/blob/main/src/protean/adapters/repository/sqlalchemy.py#L139))
and Elasticsearch
([Elasticsearch](https://github.com/proteanhq/protean/blob/main/src/protean/adapters/repository/elasticsearch.py#L43))
for examples on constructing model classes.

Once you define a base model for your provider, Protean auto-generates the model
class for aggregates or entities when needed. You can control this behavior
by supplying an explicit hand-crafted model class for your entity.

### Lookups

In Protean, lookups query the database for records that meet given criteria.
Each lookup is a custom implementation of one type of filter, which selects and
retrieves data from the database. With lookups, you can run complex queries
without writing raw SQL. Lookups are typically used in the DAO layer to fetch
records that match specific conditions.

Refer to the section on
[querying](../../guides/change-state/retrieve-aggregates.md#filtering-criteria)
aggregates for examples of lookups. Consult the documentation on your specific
chosen adapter for more information. The adapter may support specialized
lookups for efficient or technology-specific queries.

## Capabilities

Both database providers and brokers declare their **capabilities**, a set of
flags indicating which features the adapter supports. This enables:

- **Capability-gated methods**: Methods like `raw()` check automatically
  whether the provider supports them. When the provider does not, they raise
  `NotSupportedError`.
- **Automatic test selection**: Protean's conformance test suite runs only
  the tests relevant to each provider's capabilities.
- **Informed technology decisions**: Compare adapters by reading their
  capability matrices.

Database capabilities are independent of each other, so each provider supports
any combination of them. Broker capabilities are organized into hierarchical
tiers. See [Database
Capabilities](../../reference/adapters/database/index.md#database-capabilities)
and [Broker
Capabilities](../../reference/adapters/broker/index.md#broker-capabilities) for
full details.

## Provider Registry

Protean discovers providers dynamically through Python [entry
points](https://packaging.python.org/en/latest/specifications/entry-points/).
Built-in adapters register under the `protean.providers` (databases) and
`protean.brokers` (brokers) entry-point groups. Third-party adapter packages
register in the same way, making them automatically available after `pip
install`.

Entry points replace the earlier hardcoded provider dictionary. With entry
points, any installed package can register a provider as a plugin. External
packages can add new database or broker adapters without modifying Protean
source code. See [Building Custom Database
Adapters](../../reference/adapters/database/custom-databases.md) and [Building
Custom Brokers](../../reference/adapters/broker/custom-brokers.md) for guides.

## Initialization

Adapters are initialized as part of Domain initialization. Protean creates the
provider objects in the adapter. Protean then connects each provider to the
underlying infrastructure.

If Protean cannot establish a connection for any reason, initialization stops
at once and Protean exits with an error message:

```python hl_lines="9"
# fragment
--8<-- "adapters/001.py:full"
```

1. `foobar` database does not exist on port 5444

---

!!! seealso "See also"
    - [Adapter Configuration Reference](../../reference/adapters/index.md): Available adapters and their configuration options.
    - [Configuration Reference](../../reference/configuration/index.md): How to configure adapters in `domain.toml`.
    - [Building Custom Database Adapters](../../reference/adapters/database/custom-databases.md): Step-by-step guide for third-party database adapters.
    - [Building Custom Brokers](../../reference/adapters/broker/custom-brokers.md): Step-by-step guide for third-party broker adapters.
    - [Adapter Conformance Testing](../../reference/testing/conformance.md): Validate that adapters correctly implement their declared capabilities.
