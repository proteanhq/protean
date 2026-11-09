# ADR-0001: Monotonic Integer Versioning for Events

**Status:** Accepted. Compatibility semantics are settled by the schema-evolution
ladder in [ADR-0040](0040-schema-evolution-ladder.md).

**Date:** March 2026

## Context

Events and commands in Protean are messages that a consumer may read long after
a producer writes them. They are serialized, stored in event stores,
transmitted through brokers, and consumed
by handlers that may have been deployed at a different time than the producer.
When the shape of an event changes (a field is added, renamed, or removed),
consumers need to know which shape they're dealing with.

The question is how to version these messages. The two main candidates were semantic versioning
(semver: `1.0.0`, `1.1.0`, `2.0.0`) and monotonic integers (`1`, `2`, `3`).

Prior art in the event-sourcing ecosystem overwhelmingly uses simple integer versioning:
EventStoreDB uses integer version numbers for stream positions and event types. Confluent's
Schema Registry uses monotonic integer schema IDs. Apache Avro uses integer schema fingerprints.
AWS EventBridge uses integer-versioned schemas. Marten and Axon both version events with
simple integers. Semver is conspicuously absent from event versioning in production systems.

The reason is that semver's major/minor/patch semantics encode *compatibility judgments* into
the version string itself, "1.1.0 is backward-compatible with 1.0.0 but 2.0.0
is not." This embeds a policy decision into what should be a simple identity
marker.

## Decision

We will version events and commands with monotonic positive integers. The `__version__`
attribute on message classes is an integer starting at 1, incremented by 1 for a change that
needs a new version. The schema-evolution ladder (ADR-0040) lists which changes
need a new version: a structural change bumps the version. A change that weak
schema supports keeps the current version: a field added with a default, a
rename via `renamed_from`, or a removed field read leniently. The exception is
an event change that moves a Protobuf field number, which needs a new version. Upcasters apply
to stored events: an upcaster transforms an old event payload to the new
version, or the event becomes a new type when no value can be supplied.
Commands are versioned the same way, but
they are not replayed, so they carry no upcaster. The framework validates the
`__version__` integer at class creation time
in `BaseMessageType.__init_subclass__()`:

```python
class UserRegistered(BaseEvent):
    __version__ = 1
    user_id: Identifier(identifier=True)
    email: String()

# After a structural change (email becomes required): bump the version.
# A v1 -> v2 upcaster supplies `email` for old payloads (registered separately).
class UserRegistered(BaseEvent):
    __version__ = 2
    user_id: Identifier(identifier=True)
    email: String(required=True)
```

The code block above shows only the change to the `UserRegistered` class. The
v1 → v2 upcaster that supplies `email` for stored v1 payloads is registered
separately, as the [Event Upcasting guide](../guides/consume-state/event-upcasting.md)
shows.

The version appears in the message's `__type__` string as
`{Domain}.{ClassName}.v{version}` (e.g., `Auth.UserRegistered.v2`). Protean
uses the `__type__` string for runtime routing and event store lookups.
The schema-evolution ladder (ADR-0040) defines the compatibility semantics:
whether v2 is backward-compatible with v1, and how to convert between them.
Under the ladder, each change goes to weak schema (`renamed_from`, lenient
mode), an upcaster, or a new event type. The version number stays an
identity marker.

## Consequences

Versioning is simple and unambiguous. There is no debate about whether a change is a minor
or patch version: the number increments by 1 when a change needs a new version, and ADR-0040
decides which changes do. Adding an optional or defaulted field, like renaming one, does not,
unless the change moves a Protobuf field number of a field the event keeps (see the
amendment to rung 1 in ADR-0040).

The `__type__` string (`{Domain}.{ClassName}.v{version}`) is stable across code refactoring. Moving
`UserRegistered` from `auth.events` to `auth.domain.events` does not change its `__type__`,
so existing stored events remain routable. This is distinct from the FQN, which does change
on refactoring.

The trade-off is that the version number alone tells you nothing about
compatibility. Given `UserRegistered` v3, you cannot know from the number alone
whether v1 events can be read as v3. You need to inspect the change and the
evolution mechanism it uses, weak schema or an upcaster (the schema-evolution
ladder in ADR-0040). Under Protean's guiding principles (ADR-0000, principle
8), compatibility analysis belongs to tooling. The Phase 4 compatibility
checker will provide this analysis automatically.

Validation is strict: `__version__` must be a positive integer. Strings, floats, zero, and
negative numbers are rejected with `IncorrectUsageError` at class definition time, preventing
accidental misuse.

## Alternatives Considered

**Semantic versioning** was rejected because it embeds compatibility policy into the version
format. In practice, determining whether an event schema change is "breaking"
requires inspecting the actual field changes and the upcaster chain. This is
the same work the tooling does regardless of version format. Semver adds
complexity (three numbers to manage, rules about what constitutes
major/minor/patch) without reducing the need for compatibility tooling.

**String-based version tags** (e.g., `"v2-with-name-field"`) were considered
for readability but rejected for three reasons. They don't support ordering,
they make upcaster chain traversal ambiguous, and they introduce naming
convention debates.
