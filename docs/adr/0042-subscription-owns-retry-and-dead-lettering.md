# ADR-0042: The Subscription Owns Retry and Dead-Lettering

**Status:** Accepted

**Date:** September 2026

## Context

Protean has two layers that can count message failures and route a failed message somewhere final.

- The subscription layer (`BrokerSubscription` and `StreamSubscription`) counts handler failures. When a message exhausts `max_retries`, the subscription publishes it to the `{stream}:dlq` stream and acks the original.
- The InlineBroker is an in-memory test double. It has its own nack ceiling
  (`max_retries`, default 3) and its own native dead-letter queue
  (`_dead_letter_queue`). When repeated nacks cross that ceiling, the broker
  moves the message to its native DLQ.

These two layers were not reconciled. A fix for a message-loss bug (#1263) made
the subscription hold an undeliverable message: when the `{stream}:dlq` publish
fails, the subscription nacks the message to keep it pending instead of acking
it and losing it. On the InlineBroker, each nack that held a message also
counted toward the broker's own ceiling. Under a persistent `{stream}:dlq`
outage the broker eventually moved the held message to its native DLQ, so the
broker dead-lettered the message without the subscription knowing. The
subscription's `retry_counts[identifier]` was never cleared, leaking one dict
entry per message dead-lettered during the outage.

Redis Streams does not have this problem. Its nack leaves the message pending
and does no counting. Its `_max_retries` is a compatibility attribute and does
not act as a live ceiling. So on Redis Streams only the subscription layer
acts.

## Decision

Only the subscription counts retries and publishes to the DLQ.

- For a stream consumed by a subscription, the InlineBroker's nack becomes
  hold-and-redeliver with no independent ceiling, matching how Redis Streams
  already behaves. The broker no longer moves a subscription-consumed message
  to its native DLQ. Its stale-in-flight timeout sweep also holds and
  redelivers such a message instead of dead-lettering it.
- There is one dead-letter destination for a stream consumed by a subscription:
  the `{stream}:dlq` stream the subscription publishes. The broker's native
  `_dead_letter_queue` is not a second destination for them.
- The wiring is a broker hook, `_mark_subscription_owned(stream,
  consumer_group)`, on `BaseBroker`. The subscription calls it after ensuring
  the consumer group exists. The default `_mark_subscription_owned` on
  `BaseBroker` is a no-op. The InlineBroker overrides
  `_mark_subscription_owned` to record the `(stream, consumer group)` pair. In
  `_nack`, the InlineBroker skips its ceiling for recorded pairs, so it always
  holds a nacked message on those pairs and redelivers it (hold-and-redeliver).

The no-op default is correct for every production adapter. No production
adapter has an independent nack ceiling, so none can dead-letter a message
without the subscription knowing. Redis Streams holds a nacked message pending.
Redis PubSub does not support nack at all (it logs a warning and returns
`False`). So no production adapter has a second DLQ destination that the
subscription must reconcile with. Only the InlineBroker needs the
hold-and-redeliver override, because only this test double has its own ceiling.

Boundary: this covers subscription-consumed streams. When a consumer reads a
stream directly from the broker with no subscription, the InlineBroker still
counts its nacks against the ceiling and moves the message to the native DLQ.
The broker-direct path is unchanged, and its ceiling never counts a nack on the
subscription path.

## Consequences

The `retry_counts` leak is gone on the InlineBroker path. A
subscription-consumed message has one dead-letter destination, `{stream}:dlq`.
The broker no longer dead-letters a message without the subscription knowing.
So once the DLQ recovers, the subscription acks the message and clears
`retry_counts[identifier]`. While the DLQ is down, the broker holds the message
for redelivery and the `retry_counts[identifier]` entry stays set. That entry
is accurate live state and is no leak.

Production adapters are untouched: they inherit the no-op hook and keep the same nack contract.

Under a genuinely persistent `{stream}:dlq` outage the InlineBroker holds and
redelivers without bound, so a message's broker-side retry count grows. The
broker caps its exponential-backoff exponent and delay so the growing retry
count cannot overflow the exponentiation or make the wall-clock wait grow
without limit. This unbounded growth only matters in tests that drive many
rounds against a downed DLQ; set `retry_delay=0` there. In a real deployment
the DLQ usually recovers, and the subscription then acks the message.

The InlineBroker keeps its native DLQ and ceiling for the broker-direct path, so its existing broker-level retry and DLQ tests stay valid.

## Does this change break compatibility?

This is a Tier-2 behavioral change under the release and breaking-change policy
(ADR-0004). It ships without an opt-in flag.

The old behavior was observable from the public CLI. On the InlineBroker,
`_dlq_list` reports native-DLQ entries under the `{stream}:dlq` name. So under
a persistent `{stream}:dlq` publish outage, a subscription-consumed message
eventually appeared in `protean dlq list`. It no longer does: it is held and
redelivered instead.

We take the silent-correctness-bug exception in the release and breaking-change
policy (ADR-0004) and skip the three-version flag rollout. No correct program
should have depended on the old path, where two retry authorities counted the
same failure. A user has nothing to migrate. A flag that kept the old path
would keep the bug: the broker would still dead-letter messages without the
subscription knowing. The exception's "loud and immediate failure" criterion
does not apply here, since the new behavior fails by holding a message rather
than by raising. We accept that gap because the exposure is small: the
InlineBroker is an in-process, non-durable test double, and reaching the old
path needed a `{stream}:dlq` publish to keep failing inside that same process.

No public name, signature, or default changed. `BaseBroker._mark_subscription_owned` is new and concrete, defaulting to a no-op, so an existing custom broker adapter keeps working without defining it.
