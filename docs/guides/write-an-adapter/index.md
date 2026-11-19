# Write an Adapter

These guides are for a contributor who adds an adapter to Protean itself.
Protean builds its adapters in its own repository, and the conformance suites
that check an adapter live there, under `tests/conformance/`. Each guide
describes the Port the adapter implements and follows the same steps in the
same order: what the adapter implements, declare capabilities, write the
adapter, register it with an entry point, run the conformance suite, and
configure it in `domain.toml`.

- [Write an Event-Store Adapter](event-store.md): implement `EventStorePort`
  for a new event store.
