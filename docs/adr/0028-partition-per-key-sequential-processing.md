# ADR-0028: Partition-Per-Key Sequential Processing (`sequential_by`)

**Status:** Accepted

**Date:** July 2026

**Supersedes:** ADR-0009 Section 4 (which deferred `sequential_by` to the 5.2 epic)

## Context

ADR-0009 analysed concurrent event processing and decided the framework would
compose existing primitives (always-on OCC, process managers, idempotent handler
patterns) rather than add new concurrency infrastructure. Its Section 4 deferred
one feature, `sequential_by`, to the 5.2 Subscription Profiles & Tuning epic. It
named the infrastructure that feature would need (partitioned streams, a modified
publishing path, consumer-group management changes) but ratified no design for
any of it.

Epic 5.2 now revives the feature, and its two implementation issues sit blocked
on a design decision. #830 (publishing side) and #831 (consumer side) each
already assume a scheme that ADR-0009 never approved, and #831 in particular
assumes a consumer model that does not hold the guarantee it promises. This ADR
supersedes ADR-0009's deferral and pins the design so #830 and #831 can each cite
a ratified contract.

`sequential_by` gives a handler this guarantee: two *different* events that share
a partition key are never processed concurrently, and their committed effects land
in publish order. Events with different keys still run in parallel. It does not
promise exactly-once execution: delivery stays at-least-once, so the single
in-flight event a partition is working on can be redelivered and re-run on
failover. That residual duplication is the standard at-least-once case ADR-0009
already delegates to always-on OCC and idempotent handler patterns; what
`sequential_by` adds on top is the ordering and the no-concurrent-different-events
property, which OCC alone does not give.

This is the escape hatch for the cases the ADR-0009 primitives do not cover: a
single high-throughput handler that must serialize by an entity key without
collapsing all keys onto one worker. The connective pattern doc, "Designing for
Concurrent Event Processing," already routes those cases here.

Six facts about the current runtime shape every decision below. They were
confirmed against the working tree, and this is a greenfield feature (no
`sequential_by` or `partition_key` identifier exists in `src/` or `tests/` yet;
only a dormant `STREAM_PARTITIONING` capability flag and the priority-lane suffix
machinery are in place).

1. **A Redis consumer group load-balances by message, not by key.** Every engine
   instance running a handler shares one consumer group (the group name is the
   handler's FQN); only the consumer name is per-process. Redis hands different
   messages to different consumers with no key affinity, so two events for the
   same key can land on two instances and run at the same time. A shared group
   cannot serialize a key. This is the crux the consumer design must solve.
2. **The broker has no `XCLAIM`/`XAUTOCLAIM`.** `NACK` only leaves a message
   pending for redelivery to the same consumer name. Reclaiming another
   consumer's in-flight (pending) entries after a crash is not possible today.
3. **`process_batch` does not halt on failure.** On a failed message it NACKs (or
   moves to DLQ after retries) and continues to the next message in the batch.
   Under partition-per-key, the next message in a batch can be a later event for
   the same key, so continuing past a failure reorders that key under
   at-least-once retry.
4. **The reserved stream suffixes are `:dlq` and `:{backfill_suffix}`** (default
   `backfill`), both appended after the stream category. Separately, the broker
   caches consumer groups under a composite key `{stream}:{group}` and recovers the
   stream name from it by splitting on the first colon, so a stream name that
   itself contains a colon is mis-parsed. A partition stream named
   `{category}:{key}` collides with the reserved suffixes when the key is `dlq` or
   the configured backfill suffix, and trips the group-cache reverse-parse whenever
   the key (or the `{category}:{key}` shape) contains a colon.
5. **There is no keyspace scan.** Stream discovery walks the domain registry and
   deliberately avoids `SCAN`/`KEYS`. Partition keys are data-driven and not in
   the registry, so registry-walking cannot enumerate them.
6. **Routing has one choke point.** The outbox processor maps a message to its
   physical stream in one place, immediately before `broker.publish`, where the
   backfill suffix is already applied. Partition routing and key validation slot
   in there.

## Decision

We adopt **partition-per-key sequential processing** with the contract below.
`sequential_by` is the developer-facing option; partition ownership is how the
guarantee is actually kept.

### 1. Partition per key, dynamic streams

Each distinct partition-key value gets its own Redis stream,
`{stream_category}:{key}` (for example `order:client-123`). There is no fixed
partition count and no hash-based routing. The set of partitions grows with the
data. This keeps the stream name readable and debuggable in Redis, at the cost of
an unbounded partition set (addressed under discovery and consequences).

### 2. Declaring the key

`sequential_by` is a string option on the handler's metadata, supported on event
handlers and command handlers. Its value is the name of a direct attribute on the
event or command payload. Nested paths and computed keys are out of scope.

Validation runs at registration, not at publish: every event or command type the
handler handles must carry a field with that name, or registration fails loud.
This turns a whole class of "the key field was missing" runtime surprises into a
startup error.

**The partition key is a property of the stream category, not of one handler.** An
event is published once to its category and consumed by every subscriber on that
category through consumer groups, so a category is either partitioned by exactly
one key or not partitioned at all. Two handlers on the same category cannot ask for
different partition keys. All handlers on a category that declare `sequential_by`
must declare the same key; a conflict is a registration error. This is what lets
the publisher decide the partition at publish time (decision 3) from the event
alone, without knowing which handler will consume it.

**Process managers are deferred.** A PM subscribes to several categories and
correlates each event to a PM instance through a per-event `correlate` spec (which
can map a different field on each event type to the same correlation value). For a
PM, the natural serialization domain is that correlation value, not a single named
field, and aligning partitions to it across every subscribed category is its own
design problem. Rather than ratify an under-analysed semantic, v1 covers event and
command handlers only; PM support is left to a follow-up. This narrows #830's
stated scope (which listed PMs); the follow-up should decide whether a PM
partitions by correlation value and how that propagates to the categories it
shares with other handlers.

### 3. Reject unsafe and empty keys at record creation

The partition key value is extracted when the outbox record is created, in the
Unit of Work that registers the message, and validated **there**, synchronously, in
the caller's transaction. A key is rejected (fail loud, the caller's operation
fails) when it is:

- null or empty, or
- containing a colon, or
- equal to a reserved lane/DLQ token (`dlq` or the configured backfill suffix), or
- of the reserved sentinel form `__name__` (double-underscore delimited), which is
  how internal streams are named. The partition index (decision 7) uses
  `{category}:__partitions__`, so a key of `__partitions__` would collide with it;
  rejecting the whole `__*__` shape reserves that namespace for internal use and
  covers future sentinels too.

Validating at record creation, not at publish, matters: the field's *existence* is
checked at registration (decision 2), but the field's *value* is only known per
message, and the outbox publish path is asynchronous. If a bad value were allowed
to become an outbox record and only rejected at publish, that record could never
publish and would sit failing on the outbox. Validating in the caller's UoW means a
bad value fails the user's operation immediately and never enters the outbox. As a
backstop, if an invalid value ever reaches the publish path, the record is marked
`ABANDONED` at once (the existing terminal state, with an invalid-key reason) rather
than retried, so one bad record can never wedge the outbox behind it.

We reject rather than route a bad key to a default partition. A default partition
would silently coalesce unrelated keys and quietly break the ordering guarantee
for all of them, which is exactly the kind of silent corruption the framework
refuses. Real partition keys are entity identifiers (a `client_id`, an
`order_id`, a UUID), which never hit these rules, so this is a corner-case guard,
not a common-path tax. It is the same fail-loud stance the framework takes for a
missing key.

### 4. Flat stream names, collisions handled by rejection

Partition streams stay flat: `{stream_category}:{key}`. The colon and
reserved-token rejection in decision 3 is what keeps them from colliding with the
`:dlq` and `:backfill` suffixes. Because a key can never contain a colon, the
per-partition lane and DLQ names have a fixed segment count and compose
unambiguously:

- partition stream: `{stream_category}:{key}` (two segments)
- partition backfill lane: `{stream_category}:{key}:{backfill_suffix}`
- partition DLQ: `{stream_category}:{key}:dlq`

A partition stream name now carries a colon (the `category:key` shape), which the
current group-cache reverse-parse (Context fact 4, first-colon split) does not
handle. #831 must update that reverse-parse (or change the group-cache key
encoding) so a partition stream round-trips, and teach the suffix detection to
read three-segment partition lane/DLQ names. This is true whatever naming scheme
we pick, so it is not a point of difference between the options.

Where the options do differ, we rejected the structural escape (routing partitions
under a reserved infix such as `{category}:__p__:{key}`). It is collision-proof for
any key value, but it still needs colon rejection to stay unambiguous, so it does
not remove key validation; it only deepens the name. Since key validation is
unavoidable either way, the infix buys no collision-freedom the reject rule does
not already provide, and the flat name is the more readable of two designs that
carry the same parser cost.

### 5. Single active consumer per partition, by ownership with a fencing token

The guarantee is enforced by **partition ownership**, not by a per-message lock
and not by "each instance reads all partitions." Ownership is what serializes a
partition; the fence is what keeps a stale owner from corrupting order after
ownership moves. Redis Streams has no native fencing, so the fence is an
application-level lease-check, specified concretely below so #831 implements it
rather than inventing it.

**The mechanism.**

- **Lease with a generation.** A partition is owned by one engine instance at a
  time via a lease key, `{stream}:__lease__`, holding `{owner_id}:{generation}`,
  set with `NX PX <ttl>` and renewed by a heartbeat. Acquire and renew go through
  a compare-and-set script (a Lua script, so the check and the write are atomic):
  only the current `{owner_id}:{generation}` may renew; a fresh acquire after
  expiry increments the generation. Only the current owner runs a consumer for
  that partition's stream, so under normal operation there is exactly one reader
  applying that key's events strictly in order.
- **The generation is the fence.** The owner's consumer name in the group encodes
  its generation (`{owner_id}:{generation}`), and every read and ack for the
  partition is guarded by an atomic "do I still hold the lease at this generation"
  check (again a Lua script pairing the lease check with the `XREADGROUP`/`XACK`).
  A stalled-then-resumed owner whose lease has expired fails that check: it cannot
  read the next message and cannot ack, so it cannot advance the partition or
  commit out from under the new owner. This is the classic fencing token: it
  rejects the stale owner's *actions on the stream*.
- **What the fence does and does not stop.** The fence guarantees the new owner is
  the only instance that *advances* the partition, so two *different* same-key
  events are never processed concurrently and committed order is preserved. It
  does **not** un-run a handler body that a stalled owner already entered before
  it was fenced: during a stall-and-resume, the stale owner can finish executing
  the one in-flight event (its non-idempotent side effects, an email or an
  external call, are not recalled) even though its ack is then rejected. That is
  the single-in-flight-event, at-least-once duplication ADR-0009 already assigns
  to OCC and idempotent handler patterns; the stale owner never reaches the *next*
  event, so it cannot reorder the key.
- **Crash reclaim.** On owner death the lease expires and another instance claims
  the partition at a new generation and reclaims the dead owner's pending (unacked)
  entries so none are lost or skipped. Reclaiming another consumer's pending
  entries requires `XCLAIM`/`XAUTOCLAIM`, which the broker does not have today;
  adding it to the broker is part of #831's implementation of this design.
- **Horizontal scaling.** Partitions distribute across instances, so more instances
  spread ownership of more partitions rather than piling onto one stream.

This is the model Kafka (partition assignment with a generation/epoch) and Axon
(segment claims in a token store with a lease) both use to give a real per-key
ordering guarantee. Protean has prior art for atomic claim-based ownership in the
outbox `_claim` contract (ADR-0013); the partition lease is the same *pattern*
(atomic claim, single owner) on a different substrate (the broker rather than the
outbox table), not a literal reuse of that code.

We **reject a per-message distributed lock** as the enforcement mechanism. Under a
lock taken per message, if a handler runs longer than the lock's expiry a second
instance acquires the lock and processes the *next* same-key event while the first
is still on the previous one, so two different same-key events run concurrently and
their committed effects can land out of order. That is an ordering break, silent,
under exactly the load that motivated the feature. The lease-plus-fence avoids it
because the fenced stale owner can never advance to the next event; its only
residual is at-least-once re-execution of the one in-flight event, which is the
universal delivery caveat, not an ordering break. An ordering guarantee whose
correctness depends on processing time staying under a timeout is not acceptable.

#831 must implement the full ownership layer (lease with generation, the
lease-checked read/ack guard, and `XCLAIM`-based reclaim). We are not shipping a
single-instance-only interim: a guarantee that holds only until you add a second
instance is a guarantee that fails the first time it matters, and ADR-0009 deferred
this feature precisely so the infrastructure could be built correctly here.

### 6. Halt on poison

A partition halts on a message it cannot process. When a message at a partition's
head exhausts its retries, the partitioned consumer stops advancing that partition:
the message stays pending as the head, and the stall is surfaced through the
existing alerting path (the pending/lag and DLQ-alert signals) so an operator sees
it. The halt is scoped to one partition; other partitions keep flowing.

This deliberately does **not** use the shared consumer's move-to-DLQ-and-continue
behavior. That path moves the poison message to a DLQ stream and advances to the
next message, which under partition-per-key is a later event for the same key, so
it would apply a later event before an earlier one, the exact reordering
`sequential_by` exists to prevent. So for a partitioned handler, retry exhaustion
does not auto-DLQ-and-continue; it halts. Getting the partition moving again past a
poison head is an explicit operator action (inspect, then skip or move the head to
the DLQ by hand), not something the consumer does silently. This is a behavior
change from the shared `process_batch` loop, which continues past failures: the
partitioned consumer breaks that loop on an unresolved head failure instead.

### 7. Partition discovery by a maintained index

The consumer enumerates live partitions from a **maintained index**, not a
keyspace scan. On publish to `{stream_category}:{key}`, the publisher records the
key in a per-category index (a Redis set, `{stream_category}:__partitions__`). The
consumer reads the index each discovery cycle and picks up new partitions with no
restart. (The publisher may keep a per-process cache of already-recorded keys to
skip a redundant write on every publish; that is an optimization #831 can make,
not part of the contract.)

This is exact (a scan is cursor-based and only eventually consistent, and would
return the `:dlq`/`:backfill` streams to filter back out), and it matches how the
codebase already discovers streams (a runtime registry, not a scan) and how Kafka
treats partition membership (authoritative metadata, not discovered by scanning).

Cold partitions (an idle, empty stream whose key still sits in the index) must be
reaped, or the index grows without bound. Reaping has a publish/reap race: the
consumer can drop a key from the index just as a publisher re-adds it. #831 owns
the prune step and must make it safe (only reap a partition that is empty, has no
pending entries, and has been idle, and tolerate eventual re-discovery). This ties
into the epic's stream-retention work. The unbounded partition set is inherent to
partition-per-key and would exist under a scan too, so it is not a reason to
prefer scanning.

### 8. Capability gating

Partition-per-key routing is gated behind the broker's `STREAM_PARTITIONING`
capability (a flag that exists but is advertised by no broker today). A broker
that does not advertise it rejects a handler that declares `sequential_by`, fail
loud, at registration. The inline broker is single-threaded and processes
messages in submission order, so `sequential_by` is a no-op there and is treated
as satisfied; it is not an error to run a partitioned handler under the inline
broker in tests.

## Mapping each guarantee to the test #831 must pass

#831 closes on a two-instance Redis integration test whose assertions map to the
guarantees above. With two engine instances running one handler declared
`sequential_by="client_id"`, and interleaved events published for at least two
keys (`client-A`, `client-B`):

- **Strict per-key order.** For each key, the handler applies that key's events in
  published order. Assert the observed per-key sequence equals the published
  per-key sequence.
- **No concurrent entry for different same-key events.** Two different events for
  the same key never overlap in the handler. The in-progress marker must be
  **cross-instance** (recorded in Redis or the store with the instance id, not in
  process memory, or a two-instance test cannot see the overlap it exists to
  catch). Assert the marker is never held by two instances for the same key at
  once.
- **Cross-key parallelism preserved.** `client-A` and `client-B` can be in their
  handlers at the same time. Assert their processing windows overlap, so the
  feature serializes per key without serializing everything.
- **Halt on poison is partition-scoped.** A poison event at `client-A`'s head stops
  `client-A` from advancing past it (no later `client-A` event is applied) and does
  not auto-move it to a DLQ, while `client-B` keeps flowing to completion.
- **Crash failover: no loss, order preserved.** Kill the instance that owns a
  partition mid-stream. Assert another instance claims the partition, reclaims the
  dead owner's pending entries (`XCLAIM`), and resumes in strict order with no
  event lost or skipped. Apply may be at-least-once across the crash (an event
  processed but not acked before the crash is re-run), so assert order and
  no-loss, and assert final state is correct under OCC rather than asserting a
  literal single handler call per event.
- **Stall failover: the fence holds.** This is the assertion the fence exists for,
  and a kill cannot exercise it. Stall the owner past its lease (freeze its
  heartbeat) so a second instance takes the partition, then let the first resume.
  Assert the resumed stale owner cannot advance the partition or ack (its
  lease-checked read/ack is rejected), so it never reaches `client-A`'s next event
  and committed order stays intact.
- **Registration validation fails loud.** A handler declaring
  `sequential_by="client_id"` for an event type that has no `client_id` field
  fails at registration, not at publish.
- **Capability gating fails loud.** Registering a `sequential_by` handler against a
  broker that does not advertise `STREAM_PARTITIONING` raises at registration; the
  same handler under the single-threaded inline broker is accepted and behaves as a
  no-op (messages already run in submission order).
- **One partition key per category.** Two handlers on the same category declaring
  different `sequential_by` keys fail at registration.
- **Unsafe key values fail loud at record creation.** Raising an event whose key
  value is null, empty, colon-bearing, a reserved lane/DLQ token, or the
  `__partitions__` sentinel fails the caller's operation in its UoW and never
  creates an outbox record.

## Applicability and limits: when Redis is the wrong tool

Partition-per-key on Redis is bounded-cardinality by design, and that bound is a
precondition, not a footnote. The partition key must be a natural serialization
domain with a bounded live set: a tenant, a region, an account, an aggregate with
few live instances. It must **not** be a high-cardinality per-entity key (one
partition per order, per request, or per user in a large user base).

The reason is structural. Every live partition is a stream, a consumer group, an
index entry, and a share of every consumer poll cycle, so the system's standing
cost scales with the number of live partitions, not with throughput. Redis carries
this comfortably at the order of hundreds to a few thousand live partitions per
category. Past that, memory and per-cycle poll cost dominate and the cold-partition
reaper is fighting the inflow rather than keeping up. So the practical ceiling is on
the order of low thousands of live partitions per category. Treat that as a guide to
measure against, not a hard limit, and have the framework emit a warning when a
category's live partition count crosses a configurable threshold, so a
high-cardinality misuse is loud rather than a slow slide into a Redis OOM.

When a workload genuinely needs high-cardinality partitioned ordering, Redis
Streams is the wrong tool and the answer is not to push it past this regime. A
purpose-built partitioned log (Kafka and its kind) has a bounded partition count and
broker-managed partition assignment as its native model, which is exactly what
high-cardinality ordered consumption wants. Protean does not ship a Kafka broker
adapter today; if that demand is real, the right response is such an adapter that
maps `sequential_by` onto native partitions, not a reimplementation of Kafka on
Redis Streams. This ADR deliberately keeps `sequential_by` a bounded-cardinality
Redis feature and draws the line there.

EventStoreDB and MessageDB sit on a different axis and are not the escape hatch for
this ceiling. They are durable event stores (Protean already uses MessageDB), giving
per-stream ordering and durable subscriptions, not high-cardinality key fan-out with
competing consumers. Reaching past the ceiling is a broker question (a partitioned
log), not an event-store question.

Below the ceiling, and for the many cases the ADR-0009 primitives already cover
(combine handlers, a process manager, OCC retry), prefer those. `sequential_by` is
for the specific case of one handler that must serialize by a bounded key without
collapsing every key onto a single worker.

## Consequences

### Positive

- The per-key ordering guarantee is real under horizontal scaling, not just on a
  single instance, because ownership (not a shared group) is what serializes a
  partition.
- The ordering guarantee is deterministic, not probabilistic. Committed order does
  not degrade when a handler runs slowly, because nothing about the *ordering*
  depends on processing time staying under a timeout (unlike the per-message lock).
- Partition streams are readable and debuggable (`order:client-123`), and the
  reject-unsafe-keys rule keeps them from colliding with lane and DLQ streams
  without a scheme change.
- Discovery is exact and stays off the keyspace-scan path the codebase avoids.
- #830 and #831 each have a ratified contract to cite for their partition scheme,
  key handling, and ordering guarantee, and are unblocked.

### Negative

- This is the most infrastructure of the options considered: a lease with
  heartbeats, a fencing token, and `XCLAIM`-based reclaim added to the broker. It
  is more moving parts than a lock, and more than ADR-0009 wanted to add in the
  near term. The judgement is that ADR-0009 deferred the feature here so it could
  be built correctly, so building the real mechanism is on-thesis.
- The partition set is unbounded, so cold-partition reaping is required and has a
  publish/reap race that #831 must handle carefully. Worse, a high-cardinality key
  degrades quietly toward a Redis OOM rather than failing fast (see Applicability
  and limits), so the partition-count warning is a needed guardrail, not a nicety.
- Halt-on-poison stops a partition until its head message is resolved, so a stuck
  key blocks its own later events by design. That is the intended trade for
  ordering, but it means a poison message has a larger blast radius within its key
  than in a non-partitioned handler. Unwedging a halted partition needs operator
  tooling (inspect the head, then skip it or move it to the DLQ by hand) that does
  not exist yet, so that tooling is a required follow-up, not optional; without it a
  poison message on a hot key has no operator escape hatch.
- Process managers are out of v1, which narrows the epic's stated scope for #830.
  Sagas that want per-correlation ordering must wait for the follow-up that defines
  PM partitioning, or fall back to the ADR-0009 primitives in the meantime.
- The lease introduces a failover window between an owner's death and the next
  instance's claim, tunable by the lease expiry (shorter means faster failover but
  more reclaim churn; longer means the opposite).
- Delivery stays at-least-once. On a stall-and-resume or a crash-and-reclaim, the
  one in-flight event can be re-run, so non-idempotent side effects can fire twice
  for that event. `sequential_by` narrows this to the single in-flight event and
  never reorders, but it does not remove it; handlers still lean on OCC and the
  idempotent patterns from ADR-0009 for exactly-once *effect*.

## Alternatives Considered

- **Per-message distributed lock.** Simpler and stateless on failover, but its
  correctness depends on the handler finishing before the lock expires. When it
  does not, a second instance takes the lock and runs the *next* same-key event
  while the first is still on the previous one, so two different same-key events
  run concurrently and their committed effects can land out of order, silently.
  Rejected as the enforcement mechanism for a feature whose whole point is ordering.
- **Single-instance-only, defer distribution.** Ship a guarantee that holds only
  when one engine instance runs the partitioned subscription, and document the
  limit. Rejected: the guarantee fails the moment the system scales, which the
  issue explicitly called out as a thing to state and solve, not assume.
- **Fixed partition count with hashing** (Kafka's on-disk model). Bounds the
  partition set and removes discovery, but replaces readable per-key streams with
  hashed partition indices and reintroduces rebalancing across a fixed set.
  Rejected in favour of the epic's readable dynamic-stream model.
- **Discovery by keyspace scan.** The consumer runs `SCAN MATCH {category}:*` each
  cycle. Simple and needs no publisher bookkeeping, but it is only eventually
  consistent, returns reserved streams to filter out, and is the exact
  keyspace-scan pattern the codebase refuses. Rejected in favour of the maintained
  index.
- **Structural name escape (`{category}:__p__:{key}`).** Collision-proof for any
  key, but it still needs colon rejection to stay unambiguous, so it does not
  remove key validation, and it deepens every partition name by a segment for no
  gain the reject rule does not already provide. Rejected in favour of the more
  readable flat name (both schemes carry the same reverse-parse cost, per
  decision 4).
