# Broker partitioning contract

The contract a broker adapter implements to support
[`sequential_by`](../../server/sequential-by.md). This page is for **adapter
authors**. If you are using `sequential_by` with the shipped Redis Streams
adapter, you do not need anything here.

!!! info "Provisional"

    This surface is [Provisional](../../stable-surface.md): usable and
    documented, but it may change in a minor release with a changelog notice,
    until the adapter conformance suite has been exercised by an adapter that
    Protean does not maintain.

---

## What partitioning is for

`sequential_by` guarantees that events sharing a partition key are processed one
at a time, while different keys proceed in parallel. Protean implements this as
**partition-per-key** (ADR-0028): the publisher writes to `{category}:{key}`
rather than to `{category}`, and exactly one consumer owns a given key at a time.

That requires two things from the broker: a way to **discover** which partitions
exist, and a way to **own** one safely while other workers are running.

## Declaring support

A broker opts in by advertising the capability:

```python
from protean.port.broker import BaseBroker, BrokerCapabilities


class MyBroker(BaseBroker):
    @property
    def capabilities(self) -> BrokerCapabilities:
        return BrokerCapabilities.ORDERED_MESSAGING | BrokerCapabilities.STREAM_PARTITIONING
```

Without `STREAM_PARTITIONING`, `sequential_by` is a **no-op**: the publisher does
not split streams and consumers stay on the base stream with a regular
subscription. That is deliberate, so a domain declaring `sequential_by` still
runs on the inline broker in tests, without ordering guarantees.

The public methods below each call `_require_partitioning(...)` first, so an
adapter that has not declared the capability fails loudly rather than half-working.
Implement the underscore-prefixed variants (`_record_partition`,
`_partition_keys`, and so on); the public wrappers are provided.

## Discovery

| Method | Contract |
|--------|----------|
| `record_partition(category, key)` | Add `key` to the index for `category`. Called on every publish to a partition stream, so it **must be idempotent** and cheap. |
| `partition_keys(category)` | Return the live partition keys for `category`. Consumers call this each cycle to find new partitions, so it must not scan the keyspace. |
| `reap_partition(category, key, min_idle_ms, backfill_suffix=None)` | Remove a cold partition and its streams. Return `True` if reaped. |

An index rather than a keyspace scan is the point: partition keys are unbounded
(one per order, per customer), so discovery has to be O(partitions), not
O(keys in the broker).

**`reap_partition` must be atomic and conservative.** Reap only when no consumer
group on any of the partition's streams has pending entries *and* all have been
idle for at least `min_idle_ms`. When priority lanes are on, the caller passes
`backfill_suffix` so the key's backfill lane is checked and deleted with the main
stream; skipping it strands unconsumed work. Leave the generation counter in
place so a re-created partition keeps a monotonic fence. A publisher that
re-adds a key immediately after a reap is fine: it is rediscovered next cycle.

## Ownership, and why it is fenced

One owner per partition is what makes processing sequential. A lease alone is not
enough: an owner can stall (GC pause, network partition), lose its lease, and
resume mid-operation believing it still owns the partition. Both workers then
process the same key.

So ownership is **fenced**. `acquire_partition_lease` returns a monotonically
increasing generation, and every read and ack carries that token. The broker
rejects an operation whose token is older than the current generation, so a
resumed stale owner cannot act.

| Method | Contract |
|--------|----------|
| `acquire_partition_lease(lease_key, generation_key, owner_id, ttl_ms)` | Take the lease. Return the new generation, or `None` if held by someone else. Must be atomic against concurrent callers. |
| `renew_partition_lease(...)` | Extend the TTL. Return `False` if the lease was lost, which the caller treats as "stop immediately". |
| `release_partition_lease(lease_key, fence_token)` | Release on graceful shutdown. Return `False` if not held. |
| `read_partition_fenced(...)` | Read, rejecting a stale fence token. |
| `ack_partition_fenced(...)` | Ack, rejecting a stale fence token. |
| `reclaim_partition_pending(...)` | Take over entries left pending by a dead owner. |

An operation refused for a stale token raises
[`LeaseLostError`](#leaselosterror). Treat it as final: stop processing the
partition and let the next cycle re-acquire.

### `LeaseLostError`

```python
from protean.port.broker import LeaseLostError
```

Raised when a fenced operation is refused because the caller no longer owns the
partition. It is a `ProteanException`. Adapter authors raise it; consumers of
the partitioned subscription do not normally see it, because the subscription
handles it by dropping the partition.

## Stream retention

| Method | Contract |
|--------|----------|
| `trim(stream, maxlen)` | Trim `stream`, returning the number of entries removed. |

`trim` must not delete anything a consumer group still needs. The Redis adapter's
rule is worth copying: with **two or more** consumer groups, trim to the minimum
`last-delivered-id` across them and **ignore `maxlen`**, because consumer
progress bounds the stream; with **zero or one**, cap at `maxlen`. Refuse a
non-positive `maxlen` rather than emptying the stream. See
[Tuning subscriptions](../../../guides/server/tuning-subscriptions.md#stop-a-stream-from-growing-forever)
for the operator-facing consequences.

## Related reading

- [Sequential processing](../../server/sequential-by.md): the user-facing option.
- [ADR-0028](https://github.com/proteanhq/protean/blob/main/docs/adr/0028-partition-per-key-sequential-processing.md): why partition-per-key rather than a fixed partition count.
- [Stable surface](../../stable-surface.md): what Provisional means for this contract.
