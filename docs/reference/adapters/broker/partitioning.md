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

A broker opts in by advertising the capability and subclassing
`PartitioningPort` from `protean.port.broker`:

```python
--8<-- "adapters/broker/partitioning/001.py:declare"
```

On the inline broker, `sequential_by` is a **no-op**: the publisher does not
split streams and consumers stay on the base stream with a regular
subscription. That is deliberate, so a domain declaring `sequential_by` still
runs on the inline broker in tests. The inline broker processes messages one
at a time in submission order. Any other broker that does not declare
`STREAM_PARTITIONING` is rejected at `domain.init()` with `IncorrectUsageError`
when the domain declares `sequential_by`.

`PartitioningPort` extends `BrokerPort` with the nine methods in the Discovery
and Ownership tables below, and the adapter implements all of them. If a broker declares
`STREAM_PARTITIONING` and does not subclass `PartitioningPort`, `domain.init()`
raises `ConfigurationError`. The message names the methods the broker does not
implement, if any. End the adapter module with
`_PARTITIONING_CHECK: type[PartitioningPort] = YourBroker` so mypy reports a
missing or mistyped method.

The `Broker` service calls these methods. On a broker without the capability,
the service raises `NotSupportedError` before any work starts. The service
does not retry a partition call after a connection error, because a fenced
read or ack must fail when the lease is lost.

## Discovery

| Method | Contract |
|--------|----------|
| `record_partition(category, key)` | Add `key` to the index for `category`. Called on every publish to a partition stream, so it **must be idempotent** and cheap. |
| `partition_keys(category)` | Return the live partition keys for `category`. Consumers call this each cycle to find new partitions, so it must not scan the keyspace. |
| `reap_partition(category, key, min_idle_ms, backfill_suffix)` | Remove a cold partition and its streams. Return `True` if reaped. |

An index rather than a keyspace scan is the point: partition keys are unbounded
(one per order, per customer), so discovery has to be O(partitions), not
O(keys in the broker).

**`reap_partition` must be atomic and conservative.** An empty stream can always
be reaped. A stream that holds entries can be reaped only when it has at least
one consumer group, every group has read and acknowledged every entry, and its
newest entry is at least `min_idle_ms` old. Reap the partition only when each
of its streams passes this check. When priority lanes are on, the caller passes
`backfill_suffix`. The adapter then checks and deletes the key's backfill lane
together with the main stream. An adapter that skips the backfill lane leaves
unconsumed work in it. Keep the partition's lease generation counter after a
reap, so a re-created partition keeps a monotonic fence. A publisher that
re-adds a key immediately after a reap is fine: it is rediscovered next cycle.

## Ownership, and why it is fenced

One owner per partition is what makes processing sequential. A lease alone is not
enough: an owner can stall (GC pause, network partition), lose its lease, and
resume mid-operation believing it still owns the partition. The stalled owner
and the worker that took over its lease then both process the same key.

So ownership is **fenced**. `acquire_partition_lease` returns a monotonically
increasing generation. Every read and ack carries that generation as its token.
The broker rejects an operation whose token is older than the current
generation, so a resumed stale owner cannot act.

| Method | Contract |
|--------|----------|
| `acquire_partition_lease(lease_key, generation_key, owner_id, ttl_ms)` | Take the lease. Return the new generation, or `None` if held by someone else. Must be atomic against concurrent callers. |
| `renew_partition_lease(lease_key, fence_token, ttl_ms)` | Set the lease to expire `ttl_ms` milliseconds from now. Return `False` if the lease was lost, which the caller treats as "stop immediately". |
| `release_partition_lease(lease_key, fence_token)` | Release on graceful shutdown. Return `False` if not held. |
| `read_partition_fenced(stream, consumer_group, consumer_name, lease_key, fence_token, limit, new_messages)` | Read up to `limit` messages, rejecting a stale fence token. Return a list of `BrokerMessage`. |
| `ack_partition_fenced(stream, message_id, consumer_group, lease_key, fence_token)` | Ack, rejecting a stale fence token. |
| `reclaim_partition_pending(stream, consumer_group, consumer_name, min_idle_ms, limit)` | Take over the entries left pending by a dead owner, `limit` per page. Return a list of `BrokerMessage`. |

An operation refused for a stale token raises
[`LeaseLostError`](#leaselosterror). Treat it as final: stop processing the
partition and let the next cycle re-acquire.

### `LeaseLostError`

```python
--8<-- "adapters/broker/partitioning/001.py:lease_lost"
```

Raised when a fenced operation is refused because the caller no longer owns the
partition. It is a `ProteanException`. Adapter authors raise it; consumers of
the partitioned subscription do not normally see it, because the subscription
handles it by dropping the partition.

## Stream retention

Trimming has its own capability, `STREAM_RETENTION`. A broker that trims
declares it and subclasses `StreamRetentionPort` from `protean.port.broker`,
which adds one method. The same `ConfigurationError` applies when the broker
declares the flag and does not subclass the Port. On a broker without the
flag, the `Broker` service skips trimming and reports 0 entries removed.
End the adapter module with
`_STREAM_RETENTION_CHECK: type[StreamRetentionPort] = YourBroker`.

| Method | Contract |
|--------|----------|
| `trim(stream, maxlen)` | Trim `stream` toward `maxlen` entries, returning the number of entries removed. |

The Redis adapter's rule is worth copying. With **two or more** consumer groups,
it trims to the minimum `last-delivered-id` across them and **ignores
`maxlen`**, because consumer progress bounds the stream. That removes only
entries every group has had delivered, including entries delivered and not yet
acknowledged. With **zero or one** group, it caps the stream at about `maxlen`
entries. A single group more than `maxlen` entries behind then loses its oldest
unread entries, so document that limit for operators. Both trims are
approximate, so the stream can stay a little above the target. Refuse a
non-positive `maxlen` rather than emptying the stream. See
[Tuning subscriptions](../../../guides/server/tuning-subscriptions.md#stop-a-stream-from-growing-forever)
for the operator-facing consequences.

## Related reading

- [Sequential processing](../../server/sequential-by.md): The user-facing option.
- [ADR-0028](https://github.com/proteanhq/protean/blob/main/docs/adr/0028-partition-per-key-sequential-processing.md): Why partition-per-key rather than a fixed partition count.
- [Stable surface](../../stable-surface.md): What Provisional means for this contract.
