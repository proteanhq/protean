# ADR-0031: Subscription Owns Retry and Dead-Lettering

**Status:** Accepted

**Date:** August 2026

## Context

Protean supports multiple broker adapters. Each adapter has different semantics for failed messages:

- Redis Streams has no broker-native dead letter queue. The subscription layer tracks retries and publishes to `{stream}:dlq` when retries are exhausted.
- Kafka has no broker-side DLQ either. A dead letter is a record the consumer publishes to a dead-letter topic, equivalent to Protean's `{stream}:dlq` stream.
- The InlineBroker is an in-memory test double. It has its own native DLQ and an independent nack ceiling that can move a message to that native DLQ when repeated NACKs exceed the broker's budget.

This created an ambiguity when the subscription's `{stream}:dlq` publish fails but the InlineBroker later moves the held message to its own native DLQ. The message was preserved, but the subscription's `retry_counts` dict kept an entry for the dead-lettered identifier, leaking one entry per message that was dead-lettered during a DLQ outage.

## Decision

- The subscription layer owns retry counting and dead-lettering. The documented destination for exhausted messages is the subscription's published `{stream}:dlq` stream. This matches Redis Streams today and is forward-compatible with Kafka.
- The InlineBroker's native DLQ is a documented, test-only last-resort sink. It is acceptable for the InlineBroker and Redis Streams to differ here because the InlineBroker is an ephemeral test mechanism, not a production contract.
- When the InlineBroker's native DLQ takes a held message (because the subscription's DLQ publish is unavailable and the broker's own retry ceiling trips), the subscription must clear `retry_counts[identifier]`. The message is preserved in the broker's native DLQ and must not be dropped or double-handled.
- The fix is implemented by having the subscription observe the broker's native DLQ after a failed DLQ publish + NACK, not by changing the `nack`/`ack` return contract across adapters.

## Consequences

Memory no longer leaks in the InlineBroker path when messages are dead-lettered during a `{stream}:dlq` outage. The subscription's retry tracking stays accurate: it is cleared when the message leaves the subscription's control, whether by successful DLQ publish, intentional discard, or broker-native dead-lettering.

Production adapters are unaffected because they do not advertise a broker-native DLQ. The `nack`/`ack` return contract stays the same across all adapters, so no adapter needs to change its behavior to support this cleanup.

The InlineBroker continues to differ from production adapters in having a native DLQ. This is now documented as a test-only escape hatch rather than a contract every adapter must satisfy.

## Alternatives Considered

**Change `nack` to return a distinct value when it dead-letters a message.** This would let the subscription distinguish "held for retry" from "moved to native DLQ" from the return value alone. We rejected it because `nack` already returns `True` in both cases and changing that return contract would touch every adapter and every caller. Observing the broker's native DLQ keeps the change scoped to the subscription's InlineBroker-specific cleanup path.

**Move retry/DLQ ownership entirely into the broker layer.** This would require every production adapter to grow a broker-native DLQ, which contradicts how Redis Streams and Kafka actually work. It would also make the InlineBroker's test behavior part of the production contract. We rejected it because the subscription layer is the only place that can provide a consistent retry/DLQ policy across adapters.

**Leave the leak in place and document it.** We rejected this because the leak is real, unbounded, and trivial to fix once the layer ownership is settled.
