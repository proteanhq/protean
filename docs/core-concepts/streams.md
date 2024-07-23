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

