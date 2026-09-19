# ADR-0042: The Subscription Owns Retry and Dead-Lettering

**Status:** Accepted

**Date:** September 2026

## Context

Protean has two layers that can count message failures and route a failed message somewhere final.

- The subscription layer (`BrokerSubscription`) counts handler failures. When a message exhausts `max_retries`, the subscription publishes it to the `{stream}:dlq` stream and acks the original.
- The InlineBroker, an in-memory test double, has its own nack ceiling (`max_retries`, default 3) and its own native dead-letter queue (`_dead_letter_queue`). When repeated nacks cross that ceiling, the broker moves the message to its native DLQ.

These two layers were not reconciled. #1263 fixed a message-loss bug by having the subscription hold an undeliverable message: when the `{stream}:dlq` publish fails, the subscription nacks the message to keep it pending instead of acking it away. On the InlineBroker those hold-nacks fed the broker's own ceiling. Under a persistent `{stream}:dlq` outage the broker eventually moved the held message to its native DLQ, so the message took a path the subscription did not choose and could not see. The subscription's `retry_counts[identifier]` was never cleared, leaking one dict entry per message dead-lettered during the outage.

Redis Streams does not have this problem. Its nack leaves the message pending and does no counting; its `_max_retries` is a compatibility attribute, not a live ceiling. So on Redis Streams only the subscription layer acts.

## Decision

The subscription layer is the single retry and dead-lettering authority.

- For a stream consumed by a subscription, the InlineBroker's nack becomes hold-and-redeliver with no independent ceiling, matching how Redis Streams already behaves. The broker no longer moves a subscription-consumed message to its native DLQ.
- There is one dead-letter destination for these streams: the `{stream}:dlq` stream the subscription publishes. The broker's native `_dead_letter_queue` is not a second destination for them.
- The wiring is a broker hook, `_mark_subscription_owned(stream, consumer_group)`, on `BaseBroker`. `BrokerSubscription.__init__` calls it after ensuring the consumer group exists. The default is a no-op, correct for every production adapter because none has an independent ceiling. The InlineBroker overrides it to record the `(stream, consumer group)` pair and, in `_nack`, skips its ceiling for recorded pairs so they always hold-and-redeliver.

This removes the `retry_counts` leak by construction. Because the broker never dead-letters the message underneath the subscription, the subscription always sees the terminal outcome: it acks after a successful `{stream}:dlq` publish and clears `retry_counts[identifier]`.

Boundary: this covers subscription-consumed streams. A stream consumed directly off the broker with no subscription still hits the InlineBroker's ceiling and lands in the native DLQ. That path is unchanged and does not affect the subscription path.

## Consequences

The leak is gone in the InlineBroker path, and a subscription-consumed message has exactly one dead-letter destination regardless of adapter. Retry tracking stays accurate: the entry clears once the message leaves the subscription's control on ack, and stays set while the message is legitimately held for redelivery during an outage.

Production adapters are untouched: they inherit the no-op hook and keep the same nack contract.

Under a genuinely persistent `{stream}:dlq` outage the InlineBroker now holds and redelivers without bound, so a message's broker-side retry count grows and the broker's exponential backoff would grow with it. This only matters in tests that drive many rounds against a downed DLQ; set `retry_delay=0` there. In a real deployment the DLQ recovers and the message is acked.

The InlineBroker keeps its native DLQ and ceiling for the broker-direct path, so its existing broker-level retry and DLQ tests stay valid.
