# DatabasePort

The database Ports are the contract a database adapter implements.
Every database adapter implements `DatabasePort`. `RawQueryDatabasePort` adds
`raw()`, and an adapter that declares `DatabaseCapabilities.RAW_QUERIES` implements it.

A database adapter class subclasses `BaseDatabase` first, then the Port it
implements. `BaseDatabase` holds the lookup registry, the schema migrator and the
`managed` flag.

See [Database Adapters](../../reference/adapters/database/index.md) for
concrete adapter configuration, and
[Custom Database Adapters](../../reference/adapters/database/custom-databases.md)
to write one.

::: protean.port.database.DatabasePort
    options:
      show_root_heading: false

## RawQueryDatabasePort

::: protean.port.database.RawQueryDatabasePort
    options:
      show_root_heading: false

## DatabaseHealth

::: protean.port.database.DatabaseHealth
    options:
      show_root_heading: false

## BaseDatabase

::: protean.port.database.BaseDatabase
    options:
      show_root_heading: false

## DatabaseModelPort

::: protean.port.database.DatabaseModelPort
    options:
      show_root_heading: false

## DAOPort

An adapter's DAO class implements `DAOPort`, and subclasses the optional DAO
ports whose flags its database declares.

::: protean.port.dao.DAOPort
    options:
      show_root_heading: false

## RawQueryDAOPort

::: protean.port.dao.RawQueryDAOPort
    options:
      show_root_heading: false

## InsertIfAbsentPort

::: protean.port.dao.InsertIfAbsentPort
    options:
      show_root_heading: false

## NativeClaimPort

::: protean.port.dao.NativeClaimPort
    options:
      show_root_heading: false

## ClaimCandidatesPort

::: protean.port.dao.ClaimCandidatesPort
    options:
      show_root_heading: false

## BoundedDeletePort

::: protean.port.dao.BoundedDeletePort
    options:
      show_root_heading: false

## DAO

Protean wraps each adapter DAO in the `DAO` service. A repository holds the
service as `_dao`.

::: protean.infra.dao.DAO
    options:
      show_root_heading: false

## LookupPort

::: protean.port.dao.LookupPort
    options:
      show_root_heading: false

::: protean.port.dao.REQUIRED_LOOKUPS
    options:
      show_root_heading: true
