# ADR-0001: Monotonic Integer Versioning for Events

**Status:** Accepted

**Date:** March 2026

## Context

Events and commands in Protean are messages that cross time — they are serialized, stored in
event stores, transmitted through brokers, and consumed by handlers that may have been deployed
at a different time than the producer. When the shape of an event changes (a field is added,
renamed, or removed), consumers need to know which shape they're dealing with.

The question is how to version these messages. The two main candidates were semantic versioning
(semver: `1.0.0`, `1.1.0`, `2.0.0`) and monotonic integers (`1`, `2`, `3`).

Prior art in the event-sourcing ecosystem overwhelmingly uses simple integer versioning:
EventStoreDB uses integer version numbers for stream positions and event types. Confluent's
Schema Registry uses monotonic integer schema IDs. Apache Avro uses integer schema fingerprints.
AWS EventBridge uses integer-versioned schemas. Marten and Axon both version events with
simple integers. Semver is conspicuously absent from event versioning in production systems.

The reason is that semver's major/minor/patch semantics encode *compatibility judgments* into
the version string itself — "1.1.0 is backward-compatible with 1.0.0 but 2.0.0 is not." This
embeds a policy decision into what should be a simple identity marker.

## Decision

We will version events and commands with monotonic positive integers. The `__version__`
attribute on message classes is an integer starting at 1, incremented by 1 for each schema
change. The framework enforces this at class creation time in `BaseMessageType.__init_subclass__()`:

```python
class UserRegistered(BaseEvent):
    __version__ = 1
    user_id: Identifier(identifier=True)
    email: String()

# After adding a field:
class UserRegistered(BaseEvent):
    __version__ = 2
    user_id: Identifier(identifier=True)
    email: String()
    name: String(default="")
```

The version appears in the message's `__type__` string as `{Domain}.{ClassName}.{version}`
(e.g., `Auth.UserRegistered.2`), which is used for runtime routing and event store lookups.
Compatibility semantics — whether v2 is backward-compatible with v1, and how to convert
between them — are handled by the upcaster chain, not by the version number itself.

## Consequences

Versioning is simple and unambiguous. There is no debate about whether adding an optional
field is a minor or patch change. The version increments; the upcaster handles the rest.

The `__type__` string (`Domain.ClassName.version`) is stable across code refactoring. Moving
`UserRegistered` from `auth.events` to `auth.domain.events` does not change its `__type__`,
so existing stored events remain routable. This is distinct from the FQN, which does change
on refactoring.

The trade-off is that the version number alone tells you nothing about compatibility. Given
`UserRegistered` v3, you cannot know from the number alone whether v1 events can be upcast
to v3. You need to inspect the upcaster chain. This is intentional — compatibility analysis
is a tooling concern (see ADR-0000, principle 8), and the Phase 4 compatibility checker will
provide this analysis automatically.

Validation is strict: `__version__` must be a positive integer. Strings, floats, zero, and
negative numbers are rejected with `IncorrectUsageError` at class definition time, preventing
accidental misuse.

## Alternatives Considered

**Semantic versioning** was rejected because it embeds compatibility policy into the version
format. In practice, determining whether an event schema change is "breaking" requires
inspecting the actual field changes and the upcaster chain — the same work the tooling does
regardless of version format. Semver adds complexity (three numbers to manage, rules about
what constitutes major/minor/patch) without reducing the need for compatibility tooling.

**String-based version tags** (e.g., `"v2-with-name-field"`) were considered for readability
but rejected because they don't support ordering, make upcaster chain traversal ambiguous,
and introduce naming convention debates.
