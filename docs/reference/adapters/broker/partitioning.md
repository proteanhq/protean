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

`sequential_by` guarantees that events sharing a partition key are processed
one at a time. Events with different keys proceed in parallel. Protean
implements this as **partition-per-key** (ADR-0028): the publisher writes to
`{category}:{key}` instead of `{category}`. Exactly one consumer owns a given
key at a time.

That requires two things from the broker. It must let a worker **discover** the
existing partitions, and it must let a worker **own** one partition safely
alongside other running workers.

## Declaring support

A broker opts in by advertising the capability:

```python
--8<-- "adapters/broker/partitioning/001.py:declare"
```

Without `STREAM_PARTITIONING`, `sequential_by` is a **no-op**: the publisher does
not split streams and consumers stay on the base stream with a regular
subscription. That is deliberate, so a domain declaring `sequential_by` still
runs on the inline broker in tests, without ordering guarantees.

Each public method below calls `_require_partitioning(...)` first. An adapter
that has not declared the capability then raises an error on the first call
instead of running part of the contract. Implement the underscore-prefixed
variants (`_record_partition`, `_partition_keys`, and so on). Protean's base
broker class provides the public wrappers.

## Discovery

| Method | Contract |
|--------|----------|
| `record_partition(category, key)` | Add `key` to the index for `category`. Called on every publish to a partition stream, so it **must be idempotent** and cheap. |
| `partition_keys(category)` | Return the live partition keys for `category`. Consumers call this each cycle to find new partitions, so it must not scan the keyspace. |
| `reap_partition(category, key, min_idle_ms, backfill_suffix=None)` | Remove a cold partition and its streams. Return `True` if reaped. |

Discovery uses an index instead of a keyspace scan. Partition keys are
unbounded (one per order, per customer), so discovery has to be O(partitions);
a keyspace scan is O(keys in the broker).

**`reap_partition` must be atomic and conservative.** When no consumer group on
any of the partition's streams has pending entries *and* all have been idle for
at least `min_idle_ms`, reap the partition; in every other case, keep it. When
priority lanes are on, the caller passes `backfill_suffix`. The adapter then
checks and deletes the key's backfill lane together with the main stream. An
adapter that skips the backfill lane leaves unconsumed work in it. Keep the
partition's lease generation counter after a reap, so a re-created partition
keeps a monotonic fence. A publisher may re-add a key immediately after a reap.
Consumers rediscover the key on their next cycle.

## Ownership, and why it is fenced

One owner per partition is what makes processing sequential. A lease alone is
not enough: an owner can stall (GC pause, network partition), lose its lease,
and resume mid-operation believing it still owns the partition. The stalled
owner and the worker that took over its lease then both process the same key.

So ownership is **fenced**. `acquire_partition_lease` returns a monotonically
increasing generation. Every read and ack carries that generation as its token.
The broker rejects any operation with a token older than the current
generation. A stale owner that resumes therefore cannot act.

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
partition. The next cycle re-acquires the lease.

### `LeaseLostError`

```python
--8<-- "adapters/broker/partitioning/001.py:lease_lost"
```

Raised when a fenced operation is refused because the caller no longer owns the
partition. It is a `ProteanException`. Adapter authors raise `LeaseLostError`.
Consumers of the partitioned subscription do not normally see it, because the
subscription catches it and drops the partition.

## Stream retention

| Method | Contract |
|--------|----------|
| `trim(stream, maxlen)` | Trim `stream`, returning the number of entries removed. |

`trim` must not delete anything a consumer group still needs. The Redis
adapter's rule is worth copying. With **two or more** consumer groups, trim to
the minimum `last-delivered-id` across them and **ignore `maxlen`**, because
consumer progress bounds the stream. With **zero or one**, cap at `maxlen`.
Refuse a non-positive `maxlen` rather than emptying the stream. See [Tuning
subscriptions](../../../guides/server/tuning-subscriptions.md#stop-a-stream-from-growing-forever)
for the operator-facing consequences.

## Related reading

- [Sequential processing](../../server/sequential-by.md): The user-facing option.
- Partition-per-key decision record
  ([ADR-0028](https://github.com/proteanhq/protean/blob/main/docs/adr/0028-partition-per-key-sequential-processing.md)):
  Why Protean uses partition-per-key instead of a fixed partition count.
- [Stable surface](../../stable-surface.md): What Provisional means for this contract.
