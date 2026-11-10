# CachePort

The cache Ports are the contract a cache adapter implements. Every adapter
implements `CachePort`. An adapter that declares `CacheCapabilities.TTL` also
subclasses `CacheTTLPort`, and one that declares
`CacheCapabilities.PATTERN_MATCH` also subclasses `CachePatternPort`.

`domain.caches[<name>]` and `domain.cache_for(<projection>)` return a `Cache`.
`Cache` builds the keys, serializes the projections and resolves TTLs, then
calls the adapter through these Ports.

See [Cache Adapters](../../reference/adapters/cache/index.md) for
concrete adapter configuration.

::: protean.port.cache.CachePort
    options:
      show_root_heading: false

## CacheTTLPort

::: protean.port.cache.CacheTTLPort
    options:
      show_root_heading: false

## CachePatternPort

::: protean.port.cache.CachePatternPort
    options:
      show_root_heading: false

## CacheCapabilities

::: protean.port.cache.CacheCapabilities
    options:
      show_root_heading: false

## CacheHealth

::: protean.port.cache.CacheHealth
    options:
      show_root_heading: false

## Cache

::: protean.infra.cache.Cache
    options:
      show_root_heading: false
