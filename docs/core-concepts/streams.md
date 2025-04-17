# Streams

DOCUMENTATION IN PROGRESS

Streams are primary units of organization in evented systems. They serve both as storage as well as message delivery mechanism in message-based systems. When aggregates are event-sourced, they are also the principle storage medium of application entity data.

## Streams are created when a message is written to them.

Streams are created by writing a message to the stream. Messages are appended to the end of streams. If the stream doesn't exist when an event is appended to it, the event will be appended at position 0. If the stream already exists, the event will be appended at the next position number.

## Category streams are groupings of messages belonging to the same aggregate.

## Stream names must be unique.
Stream name structure.

## Stream names do not have a separate namespacing mechanism.

Stream names are not namespaced within a message store. If the same stream name must be used for different purposes, those streams should either be stored in separate message store databases, or the names of the streams should include some prefix or suffix.

## Event Streams Are Typically Safe

### Immutable, Append-Only Writes

Because all events are appended in chronological order (and never updated in place), a valid history will normally remain intact over time. Each event is written with a version number (often called an “aggregate version”), so the event store can enforce optimistic concurrency and ensure no two updates conflict or overwrite each other.

### Validation at the Aggregate

Each aggregate enforces its own invariants and rejects invalid changes before they can be turned into events. Consequently, only valid events are ever committed to the event store.

### Version Control and Concurrency Checks

When an event is appended, the system checks if the current version of the stream matches the version expected by the command (e.g., “I expect the user-205 stream to be at version 3 before adding a new event”). If they don’t match, the commit is rejected. This helps prevent partial or out-of-sequence writes.