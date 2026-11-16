# ProviderPort

The provider Ports are the contract a database adapter implements. Every
provider implements `ProviderPort`. `RawQueryProviderPort` adds `raw()`, and a
provider that declares `DatabaseCapabilities.RAW_QUERIES` implements it.

A provider class subclasses `BaseProvider` first, then the Port it implements.
`BaseProvider` holds the lookup registry, the schema migrator and the
`managed` flag.

See [Database Adapters](../../reference/adapters/database/index.md) for
concrete adapter configuration, and
[Custom Database Adapters](../../reference/adapters/database/custom-databases.md)
to write one.

::: protean.port.provider.ProviderPort
    options:
      show_root_heading: false

## RawQueryProviderPort

::: protean.port.provider.RawQueryProviderPort
    options:
      show_root_heading: false

## ProviderHealth

::: protean.port.provider.ProviderHealth
    options:
      show_root_heading: false

## BaseProvider

::: protean.port.provider.BaseProvider
    options:
      show_root_heading: false

## DatabaseModelPort

::: protean.port.provider.DatabaseModelPort
    options:
      show_root_heading: false

## DAOPort

An adapter's DAO class implements `DAOPort`, and subclasses the optional DAO
ports whose flags its provider declares.

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
