# ADR-0042: The Subscription Owns Retry and Dead-Lettering

**Status:** Accepted

**Date:** September 2026

## Context

Protean has two layers that can count message failures and route a failed message somewhere final.

- The subscription layer (`BrokerSubscription` and `StreamSubscription`) counts handler failures. When a message exhausts `max_retries`, the subscription publishes it to the `{stream}:dlq` stream and acks the original.
- The InlineBroker, an in-memory test double, has its own nack ceiling (`max_retries`, default 3) and its own native dead-letter queue (`_dead_letter_queue`). When repeated nacks cross that ceiling, the broker moves the message to its native DLQ.

These two layers were not reconciled. #1263 fixed a message-loss bug by having the subscription hold an undeliverable message: when the `{stream}:dlq` publish fails, the subscription nacks the message to keep it pending instead of acking it away. On the InlineBroker those hold-nacks fed the broker's own ceiling. Under a persistent `{stream}:dlq` outage the broker eventually moved the held message to its native DLQ, so the broker dead-lettered the message without the subscription knowing. The subscription's `retry_counts[identifier]` was never cleared, leaking one dict entry per message dead-lettered during the outage.

Redis Streams does not have this problem. Its nack leaves the message pending and does no counting; its `_max_retries` is a compatibility attribute, not a live ceiling. So on Redis Streams only the subscription layer acts.

## Decision

The subscription is the single place that counts retries and publishes to the DLQ.

- For a stream consumed by a subscription, the InlineBroker's nack becomes hold-and-redeliver with no independent ceiling, matching how Redis Streams already behaves. The broker no longer moves a subscription-consumed message to its native DLQ, and its stale-in-flight timeout sweep holds and redelivers such a message instead of dead-lettering it.
- There is one dead-letter destination for these streams: the `{stream}:dlq` stream the subscription publishes. The broker's native `_dead_letter_queue` is not a second destination for them.
- The wiring is a broker hook, `_mark_subscription_owned(stream, consumer_group)`, on `BaseBroker`. The subscription calls it after ensuring the consumer group exists. The default is a no-op. The InlineBroker overrides it to record the `(stream, consumer group)` pair and, in `_nack`, skips its ceiling for recorded pairs so they always hold-and-redeliver.

The no-op default is correct for every production adapter because none has an independent nack ceiling that could dead-letter a message underneath the subscription. Redis Streams holds a nacked message pending; Redis PubSub does not support nack at all (it logs a warning and returns `False`). So no production adapter has a second DLQ destination to reconcile; the hold-and-redeliver override is specific to the InlineBroker's test-double ceiling.

Boundary: this covers subscription-consumed streams. A stream consumed directly off the broker with no subscription still hits the InlineBroker's ceiling and lands in the native DLQ. That path is unchanged and does not affect the subscription path.

## Consequences

The leak is gone on the InlineBroker path, and a subscription-consumed message has one dead-letter destination, `{stream}:dlq`. Because the broker no longer dead-letters underneath the subscription, once the DLQ recovers the subscription acks the message and clears `retry_counts[identifier]`. While the DLQ is down the message is held for redelivery and the entry stays set, which is accurate live state, not a leak.

Production adapters are untouched: they inherit the no-op hook and keep the same nack contract.

Under a genuinely persistent `{stream}:dlq` outage the InlineBroker holds and redelivers without bound, so a message's broker-side retry count grows. The broker caps its exponential-backoff exponent and delay so the growing retry count cannot overflow the exponentiation or balloon the wall-clock wait. This unbounded growth only matters in tests that drive many rounds against a downed DLQ; set `retry_delay=0` there. In a real deployment the DLQ recovers and the message is acked.

The InlineBroker keeps its native DLQ and ceiling for the broker-direct path, so its existing broker-level retry and DLQ tests stay valid.

## Compatibility

This is a Tier-2 behavioral change under ADR-0004, and it ships without an opt-in flag.

The old behavior was observable from the public CLI. On the InlineBroker, `_dlq_list` reports native-DLQ entries under the `{stream}:dlq` name, so under a persistent `{stream}:dlq` publish outage a subscription-consumed message eventually showed up in `protean dlq list`. It no longer does: it is held and redelivered instead.

We take the silent-correctness-bug exception in ADR-0004 rather than the three-version flag rollout. The old path was two retry authorities counting the same failure, which no correct program should have depended on; there is nothing for a user to migrate; and keeping the old path alive behind a flag would keep the broker dead-lettering underneath the subscription, which is the bug. The exception's "loud and immediate failure" criterion does not apply here, since the new behavior fails by holding a message rather than by raising. We accept that gap because the exposure is small: the InlineBroker is an in-process, non-durable test double, and reaching the old path needed a `{stream}:dlq` publish to keep failing inside that same process.

No public name, signature, or default changed. `BaseBroker._mark_subscription_owned` is new and concrete, defaulting to a no-op, so an existing custom broker adapter keeps working without defining it.
