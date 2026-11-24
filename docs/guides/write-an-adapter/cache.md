# Write a Cache Adapter

To add a cache adapter to Protean, you implement `CachePort`, register the
adapter and run the cache conformance suite against it. The worked example is
`DelegatingCache`, an adapter that passes every call to the memory cache. Each
member forwards its call in one statement, so you can see the shape of the
adapter and replace each delegate call with a call to your store's client.

---

## What does the adapter implement?

A cache adapter implements `CachePort`, a `typing.Protocol` in
`protean.port.cache`. Protean's `Cache` service, which
`domain.caches[<name>]` and `domain.cache_for(<projection>)` return, builds
the keys, serializes projections and resolves TTLs before it calls the
adapter. The adapter stores JSON-ready dicts under string keys and knows
nothing about projections.

`CachePort` has these members:

- `capabilities`, a property that returns the behaviours the adapter supports
- `get`, `put` and `delete`, which read, write and remove the value under one
  key
- `clear`, which removes every entry
- `ping` and `health`, which report whether the store is reachable
- `get_connection`, which returns the store's native client, or the backing
  store for an adapter without one

`close` has a default that does nothing. When the store holds connections,
override `close`.

Two sub-protocols add members for optional behaviours:

- `CacheTTLPort` adds `set_ttl` and `get_ttl`, for per-key expiry.
- `CachePatternPort` adds `keys_matching`, `count_matching` and
  `delete_matching`, for glob patterns over keys.

The constructor takes `(name, domain, config)`, where `name` is the cache's
name in the domain configuration and `config` is its `[caches.<name>]` table.
The Protocol's constructor does not store them, so the adapter sets `name`,
`domain` and `config` itself.

The [`CachePort` reference](../../api/ports/cache.md) lists each member's
signature and what it returns or raises.

## Declare capabilities

The `capabilities` property returns a `CacheCapabilities` flag. Each flag is
a behaviour, such as `TTL`: the adapter expires each key after the number of
seconds it was given. An adapter that declares `TTL` subclasses
`CacheTTLPort`, and one that declares `PATTERN_MATCH` subclasses
`CachePatternPort`. `Domain.init()` raises `ConfigurationError` when an
adapter declares either flag and does not subclass the matching protocol.

Declare only the flags the store supports. The conformance suite runs the
tests a flag gates only when the adapter declares that flag, so a flag the
store does not support fails those tests.

The example's `capabilities` property, in the next section, returns the
memory cache's flags, `LOCAL`: `KEY_VALUE`, `TTL` and `PATTERN_MATCH`. The
memory cache does not declare `SHARED` or `DURABLE`, so the conformance suite
skips their tests. [Capabilities](../../reference/adapters/cache/index.md#capabilities)
describes the flags each built-in cache declares.

## Write the adapter

Protean's cache adapters live in `src/protean/adapters/cache/`, one module
per store. The class subclasses `CachePort`, or the sub-protocols for the
flags it declares, and sets `name`, `domain` and `config` in its constructor.
A store with a client, such as Redis, builds it in the constructor and
returns it from `get_connection()`. Each
member keeps the signature the Port gives it. The example forwards every call
to the memory cache:

```python
--8<-- "guides/write-an-adapter/cache/delegating_cache/__init__.py:class"
```

End the module with a typed assignment of the class to `CachePort`, as the
built-in caches do. When the class leaves a member abstract, mypy reports an
error on this line:

```python
--8<-- "guides/write-an-adapter/cache/delegating_cache/__init__.py:port-check"
```

## Register it with an entry point

A `register()` function adds the adapter to the cache registry,
`protean.infra.registry.caches`, under the name a domain configuration uses
as `provider`:

```python
--8<-- "guides/write-an-adapter/cache/delegating_cache/__init__.py:register"
```

Protean calls `register()` through an entry point in the `protean.caches`
group the first time it looks up a cache name. Add the entry-point line to
the `[project.entry-points."protean.caches"]` table in Protean's
`pyproject.toml`:

```toml
--8<-- "guides/write-an-adapter/cache/entry-points.toml"
```

After you edit `pyproject.toml`, run `uv sync --all-extras --all-groups`.
The installed package then lists the new entry point.

The example module also calls `register()` when it is imported, so a test run
can load it with `-p delegating_cache`. Leave that call out of your adapter.

When the store needs an optional extra, such as a client library, put
`register()` in `src/protean/adapters/cache/__init__.py`, as Redis does, and
point the entry point at it. The registry stores the class's dotted path, so
registering the name does not import the client library. Without the extra,
looking up the name then fails on the missing module instead of reporting an
unknown cache.

## Run the conformance suite

The cache conformance suite checks the adapter against the Port and against
each flag it declares. Run it from a source checkout of Protean. The suite is
in `tests/conformance/cache/`. The wheel that `pip install protean` fetches
does not include the `tests/` folder.

```shell
protean test test-adapter --port cache --provider <name>
```

`<name>` is the name `register()` uses. The command prints a row for the
tests that need no flag and a row for each flag the adapter declares. Each
flag the adapter does not declare shows as `SKIP (not declared)`. When the
store needs a connection URI or other settings, pass `--uri` or `--config`.
The suite clears the cache after each test, so point it only at a cache that
holds nothing else.

The command finds the adapter through its entry point, so the adapter must be
installed. The example is not installed, so its test run puts the example's
folder on `PYTHONPATH` and loads the module as a pytest plugin:

```shell
PYTHONPATH=docs_src/guides/write-an-adapter/cache \
    python -m pytest tests/conformance/cache -p delegating_cache \
    --port cache --adapter delegating_memory
```

[Adapter Conformance Testing](../../reference/testing/conformance.md#cli-protean-test-test-adapter)
lists every option of the command.

## Configure it in `domain.toml`

A domain selects the adapter by its registered name in a `[caches.<name>]`
table. Every domain that configures caches has a `default` cache:

```toml
--8<-- "guides/write-an-adapter/cache/domain.toml"
```

Protean passes the whole table, `provider` included, to the adapter's
constructor as `config`. The adapter reads its own settings from it, such as
the `URI` the Redis cache reads. The `Cache` service reads `TTL` itself. On
an adapter that declares `TTL`, the service passes that value to `put` when a
write names no TTL, so the adapter needs no default expiry of its own.
[Configuration](../../reference/adapters/cache/index.md#configuration)
lists the options of the built-in caches.
