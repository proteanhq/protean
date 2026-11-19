# Write an Event-Store Adapter

This guide shows how to add an event-store adapter to Protean. The worked
example is `DelegatingEventStore`, an adapter that passes every call to the
memory event store. Each member forwards its call in one statement, so you
can see the shape of the adapter and replace each delegate call with a call
to your store's client.

---

## What does the adapter implement?

An event-store adapter implements `EventStorePort`, a `typing.Protocol` in
`protean.port.event_store`. Protean's `EventStore` service, which
`domain.event_store` returns, builds aggregate loading, snapshots and message
reads on these members. Your code and the server call the service, never the
adapter directly.

The adapter implements these members:

- `capabilities`, a property that returns the guarantees the store makes
- `write_message`, which appends one message to a stream and returns its
  position in the stream
- the reads by stream, by category and over the whole store:
  `get_stream_messages`, `get_category_messages` and `get_all_messages`
- the matching reads of the newest row: `get_last_stream_message`,
  `get_last_category_message` and `get_last_message`
- `stream_ids`, which lists the stream identifiers in a category
- `ping`, `health` and `get_connection` for connection checks
- `clear`, which deletes every message, for test runs only

`close`, `create_schema` and `drop_schema` have defaults that do nothing.
When the store holds connections, override `close`. An adapter that declares
`SCHEMA_MANAGEMENT` overrides `create_schema` and `drop_schema`.

The constructor takes `(name, domain, config)`, where `config` is the
`[event_store]` table from the domain configuration. The Protocol's
constructor does not store them, so the adapter sets `name`, `domain` and
`config` itself.

The [`EventStorePort` reference](../../api/ports/event-store.md) lists each
member's signature and what it returns or raises.

## Declare capabilities

The `capabilities` property returns an `EventStoreCapabilities` flag. Each
flag is a guarantee, such as `EXPECTED_VERSION`: a write with a stale expected
version raises and writes nothing. Declare only the flags the store keeps. The
conformance suite runs the tests a flag gates only when the adapter declares
that flag, so a flag the store does not keep fails those tests.

The example's `capabilities` property, in the next section, returns the
memory store's flags. They are `CONSISTENT`, which is
`WRITE`, `READ_STREAM`, `READ_CATEGORY`, `READ_ALL`, `EXPECTED_VERSION` and
`CATEGORY_COMMIT_ORDER`. [What each event store
guarantees](../../reference/adapters/eventstore/index.md#what-each-event-store-guarantees)
describes every flag and which built-in store declares it.

## Write the adapter

Each of Protean's event-store adapters is one module in
`src/protean/adapters/event_store/`. The class subclasses `EventStorePort`, sets `name`,
`domain` and `config`, and opens the store's client in its constructor. Each
member keeps the signature `EventStorePort` gives it. The example forwards
every call to the memory store:

```python
--8<-- "guides/write-an-adapter/event-store/delegating_event_store/__init__.py:class"
```

End the module with a typed assignment of the class to `EventStorePort`, as
the built-in stores do. mypy then reports a missing or mistyped member:

```python
--8<-- "guides/write-an-adapter/event-store/delegating_event_store/__init__.py:port-check"
```

## Register it with an entry point

A `register()` function adds the adapter to the event-store registry,
`protean.infra.registry.event_stores`, under the name a domain configuration
uses as `provider`:

```python
--8<-- "guides/write-an-adapter/event-store/delegating_event_store/__init__.py:register"
```

The example calls `register()` when it is imported, so a test run can load it
with `-p delegating_event_store`. An adapter inside Protean does not call it:
Protean calls `register()` through an entry point in the
`protean.event_stores` group the first time it looks up an event-store name.
Add the entry-point line to the `[project.entry-points."protean.event_stores"]`
table in Protean's `pyproject.toml`:

```toml
--8<-- "guides/write-an-adapter/event-store/entry-points.toml"
```

After you edit `pyproject.toml`, run `uv sync --all-extras --all-groups`.
The installed package then lists the new entry point.

## Run the conformance suite

The event-store conformance suite checks the adapter against the Port and
against each flag it declares. Run it from a source checkout of Protean. The
suite is in `tests/conformance/event_store/`. The wheel that
`pip install protean` fetches does not include the `tests/` folder.

```shell
protean test test-adapter --port event_store --provider <name>
```

`<name>` is the name `register()` uses, `delegating_memory` for the example.
The command prints a row for the tests that need no flag and a row for each
flag the adapter declares. Each flag the adapter does not declare shows as
`SKIP (not declared)`. When the store needs a connection URI or other settings, pass `--uri` or
`--config`. The suite deletes every message after each
test, so point it only at a test database.

[Adapter Conformance Testing](../../reference/testing/conformance.md#cli-protean-test-test-adapter)
lists every option of the command.

## Configure it in `domain.toml`

A domain selects the adapter by its registered name in the `[event_store]`
table:

```toml
--8<-- "guides/write-an-adapter/event-store/domain.toml"
```

Protean passes the whole table, `provider` included, to the adapter's
constructor as `config`. The adapter reads its own settings from it, such as
the `database_uri` the Message DB store reads.
[Event Store Setup](../change-state/event-store-setup.md) shows the
configuration of the built-in stores.
