# Ports & Adapters Architecture

A core tenet in Protean's philosophy is to separate the domain
from the underlying infrastructure. It enables you to code
and test models without worrying about technology and plug in a
component when ready. This lets you delay your decision on technology
until [the last responsible moment](https://blog.codinghorror.com/the-last-responsible-moment/).

Protean's design is based on the [Ports and Adapters architecture](https://en.wikipedia.org/wiki/Hexagonal_architecture_(software)),
also known as Hexagonal Architecture,
allowing loosely coupled components that can be easily connected and swapped.

**Ports** are abstract interfaces that define a specific type of interaction
between the application and the outside world. They define a protocol that can
be implemented by concrete technology implementations called adapters.

**Adapters** are the glue between the application and the outside world. They
tailor the exchanges between the external technology and the ports that
represent the requirements of the inside of the application.

Protean exposes several ports with an array of built-in adapters for
each port.

## In-Memory Adapters

Every port ships with a **complete in-memory implementation** that is active
by default. These are not stubs or mocks -- they implement the full provider
interface (CRUD, filtering, sorting, stream reads, consumer groups, data
reset) using Python data structures instead of external services. This means
you can develop and test your entire domain model without any infrastructure
running.

Because memory adapters and real adapters share the same interface, you can
run the **same test suite** in both modes: in-memory for fast development
feedback, and real infrastructure for final validation. Switch with a single
flag: `pytest --protean-env memory`. See
[Dual-Mode Testing](../../patterns/dual-mode-testing.md) for the full pattern.

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
    example, `PostgreSQL` adapter that is powered by `SQLAlchemy` simply uses
    (and returns) the [sqlalchemy.orm.Session](https://docs.sqlalchemy.org/en/20/orm/session_api.html#sqlalchemy.orm.Session)
    object provided by `SQLAlchemy`.

### Provider

**Base Class**: `protean.port.database.BaseProvider`

The Provider is the main component responsible for interfacing with the
specific database technology. It contains the configuration and setup needed
to connect to the database, and it provides methods for interacting with the
database at a high level.

The Provider acts as the bridge between the application and the database,
ensuring that the necessary connections are established and maintained.
It also handles any database-specific nuances, such as connection pooling,
transaction management, and query optimization.

To add a new provider, subclass from the Provider Base class and implement
methods for your database technology.

### Data Access Object (DAO)

**Base Class**: `protean.port.database.BaseDAO`

The Data Access Object (DAO) is responsible for encapsulating the details of
the database interactions. It provides an abstract interface to the database,
hiding the complexity of the underlying database operations from the rest of
the application.

The DAO defines methods for CRUD (Create, Read, Update, Delete) operations
and other database queries, translating them into the appropriate SQL or
database-specific commands.

By using DAOs, the application code remains clean and decoupled from the
database logic. DAOs also work in conjunction in [lookups](#lookups) to
establish a query API that works across various adapters.

To add a new DAO for your provider, subclass from the DAO Base class and
implement methods for your database technology.

### Session

The Session component manages the lifecycle of database transactions. It is
responsible for opening and closing connections, beginning and committing
transactions, and ensuring data consistency.

The Session provides a context for performing database operations,
ensuring that all database interactions within a transaction are properly
managed and that resources are released appropriately. This component is
crucial for maintaining transactional integrity and for handling rollback
scenarios in case of errors.

The Session object is usually constructed and provided by the database orm
or technology package. For example, `PostgreSQL` adapter depends on the
[sqlalchemy.orm.Session](https://docs.sqlalchemy.org/en/20/orm/session_api.html#sqlalchemy.orm.Session)
object provided by `SQLAlchemy`.

### Model

**Base Class**: `protean.core.database_model.BaseDatabaseModel`

The Model represents the domain entities that are persisted in the database.
It defines the structure of the data, including fields, relationships, and
constraints. It is also a high-level abstraction for working with database
records, allowing you to interact with the data using Python objects rather
than raw queries.

Models are typically defined using a schema or an ORM
(Object-Relational Mapping) framework that maps the database tables to
Python objects.

Implementing a model for your database technology can be slightly involved,
as ORM packages can heavily depend upon internal structures. Every
database package is structured differently. Consult existing models for
PostgreSQL
([SQLAlchemy](https://github.com/proteanhq/protean/blob/main/src/protean/adapters/repository/sqlalchemy.py#L139))
and Elasticsearch
([Elasticsearch](https://github.com/proteanhq/protean/blob/main/src/protean/adapters/repository/elasticsearch.py#L43))
for examples on constructing model classes.

Once you define a base model for your provider, Protean auto-generates the model
class for aggregates or entities when needed. You can control this behavior
by supplying an explicit hand-crafted model class for your entity.

### Lookups

Lookups in Protean are mechanisms used to query the database based on certain
criteria. They are customized implementations of different types of filters
that help filter and retrieve data from the database, making it easier to
perform complex queries without writing raw SQL. Lookups are typically used in
the DAO layer to fetch records that match specific conditions.

Refer to the section on
[querying](../../guides/change-state/retrieve-aggregates.md#filtering-criteria)
aggregates for examples of lookups. Consult the documentation on your specific
chosen adapter for more information. The adapter may support specialized
lookups for efficient or technology-specific queries.

## Initialization

Adapters are initialized as part of Domain initialization. Protean creates
the provider objects in the adapter and establishes connections with the
underlying infrastructure.

If a connection cannot be established for whatever reason, the Protean
initialization procedure immediately halts and exits with an error message:

```python hl_lines="8"
{! docs_src/adapters/001.py !}
```

1. `foobar` database does not exist on port 5444

---

!!! tip "See also"
    - [Adapter Configuration Reference](../../reference/adapters/index.md) -- Available adapters and their configuration options.
    - [Configuration Reference](../../reference/configuration/index.md) -- How to configure adapters in `domain.toml`.
