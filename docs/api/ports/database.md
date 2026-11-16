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

## LookupPort

::: protean.port.dao.LookupPort
    options:
      show_root_heading: false

::: protean.port.dao.REQUIRED_LOOKUPS
    options:
      show_root_heading: true
