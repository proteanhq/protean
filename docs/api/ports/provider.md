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

## LookupPort

::: protean.port.dao.LookupPort
    options:
      show_root_heading: false

::: protean.port.dao.REQUIRED_LOOKUPS
    options:
      show_root_heading: true
