# ADR-0028: Partition-Per-Key Sequential Processing (`sequential_by`)

**Status:** Accepted

> Amended October 2026, see the
[projectors amendment](#amendment-october-2026-projectors) and the
[outbox-side ordering amendment](#amendment-october-2026-outbox-side-ordering)
below.

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

`sequential_by` gives a handler this guarantee: two *different* events that
share a partition key are never processed concurrently, and their effects are
committed in publish order. Events with different keys still run in parallel.
`sequential_by` does not promise exactly-once execution: delivery stays
at-least-once, so the single in-flight event a partition is working on can be
redelivered and re-run on failover. Under ADR-0009, always-on OCC and
idempotent handler patterns already cover that remaining duplication, the
standard at-least-once case. On top of that, `sequential_by` adds two
properties that OCC alone does not give: the ordering, and the
no-concurrent-different-events property.

`sequential_by` is for the cases the ADR-0009 primitives do not cover: a single
high-throughput handler that must serialize by an entity key without collapsing
all keys onto one worker. The connective pattern doc, "Designing for Concurrent
Event Processing," already routes those cases here.

Six facts about the current runtime shape every decision below. We confirmed
these facts against the working tree. `sequential_by` is a greenfield feature:
no `sequential_by` or `partition_key` identifier exists in `src/` or `tests/`
yet, and only a dormant `STREAM_PARTITIONING` capability flag and the
priority-lane suffix machinery are in place.

1. **A Redis consumer group load-balances by message, not by key**: Every engine
   instance running a handler shares one consumer group (the group name is the
   handler's FQN); only the consumer name is per-process. Redis delivers
   different messages to different consumers with no key affinity, so two
   instances can receive two events for the same key and run them at the same
   time. A shared group cannot serialize a key. This is the central problem the
   consumer design must solve.
2. **The broker has no `XCLAIM`/`XAUTOCLAIM`**: `NACK` only leaves a message
   pending for redelivery to the same consumer name. Reclaiming another
   consumer's in-flight (pending) entries after a crash is not possible today.
3. **`process_batch` does not halt on failure**: On a failed message it NACKs (or
   moves to DLQ after retries) and continues to the next message in the batch.
   Under partition-per-key, the next message in a batch can be a later event for
   the same key, so continuing past a failure reorders that key under
   at-least-once retry.
4. **The reserved stream suffixes are `:dlq` and `:{backfill_suffix}`** (default
   `backfill`), both appended after the stream category. Separately, the broker
   caches consumer groups under a composite key `{stream}:{group}` and recovers
   the stream name by splitting that key on the first colon. As a result, the
   broker mis-parses any stream name that itself contains a colon. A partition
   stream named `{category}:{key}` collides with the reserved suffixes when the
   key is `dlq` or the configured backfill suffix. The same stream breaks the
   group-cache reverse-parse whenever the key (or the `{category}:{key}` shape)
   contains a colon.
5. **Stream discovery does not scan the keyspace**: The broker discovers streams by
   walking the domain registry and deliberately avoids `SCAN`/`KEYS` for that. (The
   Redis cache adapter does use `SCAN` for its own key lookups; the point here is
   scoped to stream and broker discovery.) Partition keys are data-driven and not in
   the registry, so registry-walking cannot enumerate them.
6. **Routing has one choke point**: The outbox processor maps a message to its
   physical stream in one place, immediately before `broker.publish`, where the
   backfill suffix is already applied. The outbox processor will also apply
   partition routing and the backstop key check at that point.

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

`sequential_by` is an option on the handler's metadata, supported on event
handlers, command handlers, and process managers (and projectors, see the
[amendment](#amendment-october-2026-projectors) at the end of this record). On
an event or command handler its value is the name of a direct attribute on the event or command payload; nested
paths and computed keys are out of scope. On a process manager it is a boolean
opt-in, because a PM already declares its serialization domain through its
`correlate` specs (see below).

Validation runs at registration, not at publish: every event or command type the
handler handles must carry a field with that name, or registration fails loud.
This turns a whole class of "the key field was missing" runtime surprises into a
startup error.

**The partition key is a property of the stream category, not of one handler.** An
event is published once to its category and consumed by every subscriber on that
category through consumer groups, so a category is either partitioned by exactly
one key or not partitioned at all. Two handlers on the same category cannot ask for
different partition keys. All handlers on a category that declare `sequential_by`
must declare the same key; a conflict is a registration error. One key per
category lets the publisher decide the partition at publish time (decision 3)
from the event alone, without knowing which handler will consume it.

**Process managers partition by correlation value.** A PM subscribes to several
categories and correlates each event to a PM instance through a per-event
`correlate` spec, which can map a different field on each event type to the same
correlation value. So a PM's natural serialization domain is not a single named
field, it is the correlation value the PM already resolves. With
`sequential_by` set on a PM, the partition key on each subscribed category is
the field `correlate` maps to the correlation value there (`order` partitioned
by `order_id`, `payment` partitioned by the field that maps to `order_id`). As
a result, every event for one PM instance carries the same correlation value
across those categories.

For a PM, the guarantee covers the instance and promises no total order: **no
two events for the same PM instance are ever processed concurrently.** Strict
cross-category publish order is not well defined (the events live on different
streams), and a PM does not need it. A PM is an eventually-consistent
coordinator whose instance is a stateful aggregate, so OCC already makes it
correct across arrival orders. `sequential_by` adds serialization: it stops the
PM from handling two events for the same instance at once. That serialization
removes the OCC-thrash and the concurrent-handler races a busy PM would
otherwise hit.

Ownership for a PM is therefore keyed by the correlation value and spans the PM's
subscribed category partitions: one instance leases correlation value `X` and is the
sole processor of `order:X`, `payment:X`, and so on, applying them one at a time.
This reuses the lease and fence of decision 5, keyed by correlation rather than by a
single stream. A PM's categories are now partitioned by the correlation field,
so the one-key-per-category rule above binds every other handler on those
categories. Such a handler must partition by the same field or not partition at
all, or Protean raises a registration error. Enabling `sequential_by` on a PM
is thus a decision about the categories it subscribes to, not the PM alone.

### 3. Reject unsafe and empty keys at record creation

The Unit of Work that registers the message extracts the partition key value as
it creates the outbox record. It validates the value **there**, synchronously,
in the caller's transaction. A key is rejected (fail loud, the caller's
operation fails) when it is:

- null or empty, or
- containing a colon, or
- equal to a reserved lane/DLQ token (`dlq` or the configured backfill suffix), or
- of the reserved sentinel form `__name__` (double-underscore delimited), which is
  how internal streams are named. The partition index (decision 7) uses
  `{category}:__partitions__`, so a key of `__partitions__` would collide with
  it. Protean rejects the whole `__*__` shape, which reserves that namespace
  for internal use and covers future sentinels too.

Protean checks the field's *existence* at registration (decision 2), but it
knows the field's *value* only per message. The outbox publish path is
asynchronous, so Protean must check the value at record creation, before
publish. If a bad value were allowed to become an outbox record and only
rejected at publish, that record could never publish and would sit failing on
the outbox. Validating in the caller's UoW means a bad value fails the user's
operation immediately and never enters the outbox. As a backstop, the outbox
processor marks a record `ABANDONED` at once (the existing terminal state, with
an invalid-key reason) when an invalid value reaches the publish path. The
processor does not retry that record, so it does not fail over and over. The
abandoned record keeps its key, so that key's later records wait until an
operator re-queues the record or marks it published. Other keys keep flowing.

We reject rather than route a bad key to a default partition. A default partition
would silently coalesce unrelated keys and quietly break the ordering guarantee
for all of them, which is exactly the kind of silent corruption the framework
refuses. Real partition keys are entity identifiers (a `client_id`, an
`order_id`, a UUID), which these rules never reject, so the rejection guards a
corner case and adds no cost on the common path. It is the same fail-loud
stance the framework takes for a missing key.

### 4. Flat stream names, collisions handled by rejection

Partition streams stay flat: `{stream_category}:{key}`. The colon and
reserved-token rejection in decision 3 is what keeps them from colliding with the
`:dlq` and `:backfill` suffixes. Because a key can never contain a colon, the
per-partition lane and DLQ names have a fixed segment count and compose
unambiguously:

- partition stream: `{stream_category}:{key}` (two segments)
- partition backfill lane: `{stream_category}:{key}:{backfill_suffix}`
- partition DLQ: `{stream_category}:{key}:dlq`

A partition stream name now carries a colon (the `category:key` shape), and the
current group-cache reverse-parse (Context fact 4, first-colon split)
mis-parses it. #831 must update that reverse-parse (or change the group-cache
key encoding) so a partition stream round-trips, and must make the suffix
detection read three-segment partition lane/DLQ names. This is true whatever
naming scheme we pick, so it is not a point of difference between the options.

Where the options do differ, we rejected the structural escape (routing partitions
under a reserved infix such as `{category}:__p__:{key}`). The structural escape
is collision-proof for any key value, but it still needs colon rejection to
stay unambiguous. So the escape keeps key validation and only adds a segment to
the name. Both schemes need key validation, so the infix adds no collision
protection beyond the reject rule. They also carry the same parser cost, and
the flat name is the more readable of the two.

### 5. Single active consumer per partition, by ownership with a fencing token

The guarantee is enforced by **partition ownership**, not by a per-message lock
and not by "each instance reads all partitions." Ownership is what serializes a
partition; the fence is what keeps a stale owner from corrupting order after
ownership moves. Redis Streams has no native fencing, so the fence is an
application-level lease-check. We specify the check concretely below, so #831
can implement it as written.

**The mechanism.**

- **Lease with a generation**: One engine instance at a time owns a partition
  through a lease key, `{stream}:__lease__`, that holds
  `{owner_id}:{generation}`. The owner sets the key with `NX PX <ttl>` and
  renews it with a heartbeat. Acquire and renew go through a compare-and-set
  script (a Lua script, so the check and the write are atomic): only the
  current `{owner_id}:{generation}` may renew; a fresh acquire after expiry
  increments the generation. Only the current owner runs a consumer for that
  partition's stream, so under normal operation there is exactly one reader
  applying that key's events strictly in order.
- **The generation is the fence**: The owner's consumer name in the group
  encodes its generation (`{owner_id}:{generation}`). An atomic "do I still
  hold the lease at this generation" check guards every read and ack for the
  partition (again a Lua script pairing the lease check with the
  `XREADGROUP`/`XACK`). When a stalled owner resumes after its lease expired,
  it fails that check and can neither read the next message nor ack. So the
  stale owner cannot advance the partition or commit while the new owner holds
  it. This is the classic fencing token: it rejects the stale owner's *actions
  on the stream*.
- **What the fence does and does not stop**: The fence guarantees the new owner is
  the only instance that *advances* the partition, so two *different* same-key
  events are never processed concurrently and committed order is preserved. It
  does **not** un-run a handler body that a stalled owner already entered
  before it was fenced. During a stall-and-resume, the stale owner can finish
  executing the one in-flight event (its non-idempotent side effects, an email
  or an external call, are not recalled) even though its ack is then rejected.
  That is the single-in-flight-event, at-least-once duplication ADR-0009
  already assigns to OCC and idempotent handler patterns. The stale owner never
  reaches the *next* event, so it cannot reorder the key.
- **Crash reclaim**: On owner death the lease expires and another instance claims
  the partition at a new generation and reclaims the dead owner's pending (unacked)
  entries so none are lost or skipped. Reclaiming another consumer's pending
  entries requires `XCLAIM`/`XAUTOCLAIM`, which the broker does not have today;
  adding it to the broker is part of #831's implementation of this design.
- **Horizontal scaling**: Partitions distribute across instances, so more instances
  spread ownership of more partitions rather than piling onto one stream.

Kafka (partition assignment with a generation/epoch) and Axon (segment claims
in a token store with a lease) both use this lease-and-fence model to give a
real per-key ordering guarantee. Protean already uses atomic claim-based
ownership in the outbox `_claim` contract (ADR-0013). The partition lease
follows the same *pattern* (atomic claim, single owner) on the broker instead
of the outbox table, and it does not reuse that code.

We **reject a per-message distributed lock** as the enforcement mechanism.
Under a lock taken per message, a handler can run longer than the lock's
expiry. A second instance then acquires the lock and processes the *next*
same-key event while the first is still on the previous one, so two different
same-key events run concurrently and can commit their effects out of order.
That is an ordering break, silent, under exactly the load that motivated the
feature. The lease-plus-fence avoids that ordering break because the fence
stops the stale owner from advancing to the next event. The only remaining risk
is at-least-once re-execution of the one in-flight event, the universal
delivery caveat, and that re-run does not break ordering. We do not accept an
ordering guarantee whose correctness depends on processing time staying under
a timeout.

Issue #831 must implement the full ownership layer (lease with generation, the
lease-checked read/ack guard, and `XCLAIM`-based reclaim). We are not shipping
a single-instance-only interim, because a guarantee that holds only until you
add a second instance fails the first time it matters. ADR-0009 deferred this
feature precisely so the infrastructure could be built correctly here.

### 6. Halt on poison

A partition halts on a message it cannot process. When a message at a
partition's head exhausts its retries, the partitioned consumer stops advancing
that partition and leaves the message pending as the head. The existing
alerting path (the pending/lag and DLQ-alert signals) reports the stall to an
operator. The halt is scoped to one partition; other partitions keep flowing.

This deliberately does **not** use the shared consumer's move-to-DLQ-and-continue
behavior. The shared path moves the poison message to a DLQ stream and advances
to the next message, which under partition-per-key is a later event for the
same key. The consumer would then apply a later event before an earlier one,
the exact reordering that `sequential_by` prevents. So for a partitioned
handler, retry exhaustion does not auto-DLQ-and-continue; it halts. An operator
advances the partition past a poison head by an explicit action (inspect, then
skip or move the head to the DLQ by hand), and the consumer never does this
silently. The halt is a behavior change from the shared `process_batch` loop,
which continues past failures: the partitioned consumer breaks that loop on an
unresolved head failure instead.

### 7. Partition discovery by a maintained index

The consumer enumerates live partitions from a **maintained index**, not a
keyspace scan. On publish to `{stream_category}:{key}`, the publisher records the
key in a per-category index (a Redis set, `{stream_category}:__partitions__`). The
consumer reads the index each discovery cycle and picks up new partitions with no
restart. (The publisher may keep a per-process cache of already-recorded keys
to skip a redundant write on every publish. That cache is an optimization #831
can make, and the contract does not require it.)

The index gives an exact partition list, while a scan is cursor-based, only
eventually consistent, and would return the `:dlq`/`:backfill` streams to
filter back out. The index also matches how the codebase already discovers
streams (a runtime registry, with no scan) and how Kafka treats partition
membership (authoritative metadata, found without scanning).

The consumer must reap cold partitions (an idle, empty stream whose key still
remains in the index), or the index grows without bound. Reaping has a
publish/reap race: the consumer can drop a key from the index just as a
publisher re-adds it. #831 owns the prune step and must make it safe (only reap
a partition that is empty, has no pending entries, and has been idle, and
tolerate eventual re-discovery). This ties into the epic's stream-retention
work. The unbounded partition set is inherent to partition-per-key and would
exist under a scan too, so it is not a reason to prefer scanning.

### 8. Capability gating

Partition-per-key routing is gated behind the broker's `STREAM_PARTITIONING`
capability (a flag that exists but is advertised by no broker today). A broker
that does not advertise it rejects a handler that declares `sequential_by`, fail
loud, at registration. The inline broker is single-threaded and processes
messages in submission order, so `sequential_by` is a no-op there and is treated
as satisfied; it is not an error to run a partitioned handler under the inline
broker in tests.

## Mapping each guarantee to the test #831 must pass

Issue #831 closes on a two-instance Redis integration test whose assertions map
to the guarantees above. With two engine instances running one handler declared
`sequential_by="client_id"`, and interleaved events published for at least two
keys (`client-A`, `client-B`):

- **Strict per-key order**: For each key, the handler applies that key's events in
  published order. Assert the observed per-key sequence equals the published
  per-key sequence.
- **No concurrent entry for different same-key events**: Two different events for
  the same key never overlap in the handler. The in-progress marker must be
  **cross-instance**, recorded in Redis or the store with the instance id. If
  the marker is kept in process memory, a two-instance test cannot see the
  overlap the marker exists to catch. Assert the marker is never held by two
  instances for the same key at once.
- **Cross-key parallelism preserved**: `client-A` and `client-B` can be in their
  handlers at the same time. Assert their processing windows overlap, so the
  feature serializes per key without serializing everything.
- **Halt on poison is partition-scoped**: A poison event at `client-A`'s head
  stops `client-A` from advancing past it (no later `client-A` event is
  applied), and the consumer does not auto-move the event to a DLQ. Meanwhile
  `client-B` keeps flowing to completion.
- **Crash failover: no loss, order preserved**: Kill the instance that owns a
  partition mid-stream. Assert another instance claims the partition, reclaims the
  dead owner's pending entries (`XCLAIM`), and resumes in strict order with no
  event lost or skipped. Apply may be at-least-once across the crash (an event
  processed but not acked before the crash is re-run). So assert order, no
  loss, and a correct final state under OCC, and do not assert a literal single
  handler call per event.
- **Stall failover: the fence holds**: This is the assertion the fence exists for,
  and a kill cannot exercise it. Stall the owner past its lease (freeze its
  heartbeat) so a second instance takes the partition, then let the first resume.
  Assert the resumed stale owner cannot advance the partition or ack (its
  lease-checked read/ack is rejected), so it never reaches `client-A`'s next event
  and committed order stays intact.
- **Registration validation fails loud**: A handler declaring
  `sequential_by="client_id"` for an event type that has no `client_id` field
  fails at registration, not at publish.
- **Capability gating fails loud**: Registering a `sequential_by` handler against a
  broker that does not advertise `STREAM_PARTITIONING` raises at registration; the
  same handler under the single-threaded inline broker is accepted and behaves as a
  no-op (messages already run in submission order).
- **One partition key per category**: Two handlers on the same category declaring
  different `sequential_by` keys fail at registration. Registration also fails
  for a handler that partitions a category by a field different from a
  `sequential_by` PM's correlation field on the same category.
- **Process manager serializes per instance**: Run a PM correlated by
  `order_id` across the `order` and `payment` categories, and publish
  interleaved order and payment events for two correlation values. Assert that
  no two events for the same correlation value are ever in the PM handler at
  once (cross-instance marker), and that different correlation values progress
  in parallel. Order and payment events for one instance need not apply in a
  strict cross-category order, only never concurrently.
- **Unsafe key values fail loud at record creation**: When an event's key value
  is null, empty, colon-bearing, a reserved lane/DLQ token, or the
  `__partitions__` sentinel, raising the event fails the caller's operation in
  its UoW and never creates an outbox record.

## Applicability and limits: when Redis is the wrong tool

Partition-per-key on Redis is bounded-cardinality by design, and staying within
that bound is a precondition for using the feature. The partition key must be a
natural serialization domain with a bounded live set: a tenant, a region, an
account, an aggregate with few live instances. It must **not** be a
high-cardinality per-entity key (one partition per order, per request, or per
user in a large user base).

The reason is structural. Every live partition is a stream, a consumer group, an
index entry, and a share of every consumer poll cycle, so the system's standing
cost scales with the number of live partitions, not with throughput. Redis carries
this comfortably at the order of hundreds to a few thousand live partitions per
category. Beyond that range, memory and per-cycle poll cost dominate. The
cold-partition reaper then removes partitions more slowly than new ones arrive.
So the practical ceiling is on the order of low thousands of live partitions
per category. Treat that as a guide to measure against and not as a hard limit.
Have the framework emit a warning when a category's live partition count
crosses a configurable threshold, so an operator sees a high-cardinality misuse
before Redis runs out of memory.

When a workload genuinely needs high-cardinality partitioned ordering, Redis
Streams is the wrong tool and the answer is not to push it past this regime. A
purpose-built partitioned log (Kafka and its kind) has a bounded partition
count and broker-managed partition assignment as its native model, and that
model fits high-cardinality ordered consumption exactly. Protean does not ship
a Kafka broker adapter today. If that demand is real, the right response is a
Kafka adapter that maps `sequential_by` onto native partitions, and a
reimplementation of Kafka on Redis Streams is the wrong one. This ADR
deliberately keeps `sequential_by` a bounded-cardinality Redis feature and
draws the line there.

EventStoreDB and MessageDB solve a different problem and offer no way past this
ceiling. They are durable event stores (Protean already uses MessageDB), giving
per-stream ordering and durable subscriptions, not high-cardinality key fan-out
with competing consumers. A workload past the ceiling needs a different broker
(a partitioned log), and a different event store does not help.

Below the ceiling, and for the many cases the ADR-0009 primitives already cover
(combine handlers, a process manager, OCC retry), prefer those. `sequential_by` is
for the specific case of one handler that must serialize by a bounded key without
collapsing every key onto a single worker.

## Consequences

### Positive

- The per-key ordering guarantee holds under horizontal scaling as well as on a
  single instance, because ownership (not a shared group) serializes
  each partition.
- The ordering guarantee is deterministic, not probabilistic. Committed order does
  not degrade when a handler runs slowly, because nothing about the *ordering*
  depends on processing time staying under a timeout (unlike the per-message lock).
- Partition streams are readable and debuggable (`order:client-123`), and the
  reject-unsafe-keys rule keeps them from colliding with lane and DLQ streams
  without a scheme change.
- Discovery is exact and uses no keyspace scan, which the codebase avoids.
- Issues #830 and #831 each have a ratified contract to cite for their
  partition scheme, key handling, and ordering guarantee, and are unblocked.

### Negative

- This is the most infrastructure of the options considered: a lease with
  heartbeats, a fencing token, and `XCLAIM`-based reclaim added to the broker. It
  is more moving parts than a lock, and more than ADR-0009 wanted to add in the
  near term. ADR-0009 deferred the feature here so it could be built correctly,
  and we judge that building the real mechanism fits that intent.
- The partition set is unbounded, so cold-partition reaping is required,
  and #831 must make the reap step safe against its publish/reap race. Worse, a
  high-cardinality key slowly drives Redis toward running out of memory (OOM)
  and does not fail fast (see Applicability and limits). So the partition-count
  warning is a required safeguard.
- Halt-on-poison stops a partition until its head message is resolved, so a stuck
  key blocks its own later events by design. That is the intended trade for
  ordering, but it means a poison message has a larger blast radius within its key
  than in a non-partitioned handler. To restart a halted partition, an operator
  needs tooling (inspect the head, then skip it or move it to the DLQ by hand)
  that does not exist yet. That tooling is a required follow-up, because
  without it an operator cannot clear a poison message on a hot key.
- Process-manager support couples categories together. When a PM sets
  `sequential_by`, Protean partitions every category the PM subscribes to by
  the PM's correlation field. All other handlers on those categories must then
  use the same key (the one-key-per-category rule). Enabling `sequential_by` on
  a PM is a decision about the shared categories as well as the PM. A
  co-subscriber that wants a different partitioning of one of those categories
  cannot have it.
- A PM's ownership lease spans several category partition streams for one
  correlation value, more than the single-stream lease a handler needs. #831
  must key the lease and the fence by correlation value and have the owner read
  every partition stream of that correlation.
- The lease introduces a failover window between an owner's death and the next
  instance's claim, tunable by the lease expiry (shorter means faster failover but
  more reclaim churn; longer means the opposite).
- Delivery stays at-least-once. On a stall-and-resume or a crash-and-reclaim, the
  one in-flight event can be re-run, so non-idempotent side effects can fire twice
  for that event. `sequential_by` limits the re-run to the single in-flight
  event and never reorders, but it does not remove the re-run. Handlers still
  depend on OCC and the idempotent patterns from ADR-0009 for
  exactly-once *effect*.

## Alternatives Considered

- **Per-message distributed lock**: Simpler and stateless on failover, but its
  correctness depends on the handler finishing before the lock expires. When
  the handler runs past the lock's expiry, a second instance takes the lock and
  runs the *next* same-key event while the first is still on the previous one.
  Two different same-key events then run concurrently, and they can commit
  their effects out of order without any error. Rejected as the enforcement
  mechanism for a feature whose whole point is ordering.
- **Single-instance-only, defer distribution**: Ship a guarantee that holds only
  when one engine instance runs the partitioned subscription, and document the
  limit. Rejected: the guarantee fails as soon as a second instance runs, and
  the issue explicitly asked for scaling to be stated and solved instead
  of assumed.
- **Fixed partition count with hashing** (Kafka's on-disk model). Bounds the
  partition set and removes discovery, but replaces readable per-key streams with
  hashed partition indices and reintroduces rebalancing across a fixed set.
  Rejected in favour of the epic's readable dynamic-stream model.
- **Discovery by keyspace scan**: The consumer runs `SCAN MATCH {category}:*` each
  cycle. Simple and needs no publisher bookkeeping, but it is only eventually
  consistent, returns reserved streams to filter out, and is the exact
  keyspace-scan pattern the broker's stream discovery avoids. Rejected in favour of
  the maintained index.
- **Structural name escape (`{category}:__p__:{key}`)**: Collision-proof for any
  key, but it still needs colon rejection to stay unambiguous, so it does not
  remove key validation, and it deepens every partition name by a segment for no
  gain the reject rule does not already provide. Rejected in favour of the more
  readable flat name (both schemes carry the same reverse-parse cost, per
  decision 4).

## Amendment (October 2026): projectors

Decision 2 listed event handlers, command handlers and process managers. Users
could not declare ordering on a projector whose category no other handler
partitions, even though the consumer already reads a partitioned category
partition by partition for every stream-subscribed handler on it.

**Amended decision:** projectors also accept `sequential_by`, with the
event-handler meaning. The value names a direct field on every event the
projector handles. Each handled event's published category is partitioned by that
field. The same registration rules apply: field existence, one key per category
(shared with every other handler on the category), and broker capability. The
process-manager boolean form does not apply to projectors. The ordering holds
for a projector on a stream subscription. An event-store subscription reads the
event store directly, so `sequential_by` does not change its behaviour.
Ordering is per stream category, so a projector over several aggregates is not
ordered across their categories.

## Amendment (October 2026): outbox-side ordering

The consumer kept a key's events in publish order, but the outbox did not
publish them in commit order. The claim sorts rows by priority and then by
commit order, but it claimed each row on its own. A failed row was retried
later while the rows behind it published, and two workers could publish one
key's rows at the same time. The consumer then applied a key's
events out of commit order.

**Amended decision:** the outbox holds a partitioned row back until every
earlier row of its group has published.

- **Commit order** is `created_at`, then `sequence_number`, the event's
  position within its Unit of Work commit. The claim orders rows by
  `-priority`, `created_at`, `sequence_number`, `id`. Rows of one key that
  commit concurrently are ordered by `created_at`, which is not always the
  order in which their commits became visible (see the limits below).
- **The group is the destination stream:** `(target_broker, stream_category,
  partition_key, lane)`. The lane is backfill when priority lanes are enabled,
  the row targets the internal broker, and its priority is below the threshold.
  Every other row is in the primary lane. The two lanes and the different
  brokers are separate streams with no order promised between them, so a row
  in one never holds a row in another. Rows without a partition key are never
  held.
- **The outbox row stores its stream category.** The Unit of Work and the
  reconciliation sweep copy `metadata.domain.stream_category` into a new
  `stream_category` column, so the claim query can compare it and an index
  (`ix_outbox_hold_back`) can cover it. A row with no stream category is not
  grouped.
- **The claim rule.** A row is claimable only when every earlier row of its
  group that is `pending`, `processing`, `failed` or `abandoned` is claimed in
  the same call. One claim can therefore take a run of rows from one group. A
  row another worker has locked, a failed row whose retry is not due, and an
  abandoned row all hold the rows behind them.
- **Candidates are narrowed before the limit applies.** A row is a candidate
  only when every earlier holding row of its group is itself claimable now and
  sorts before it in the claim order. Without that, a halted key with more
  rows than the batch size would fill every batch and starve other keys, and a
  later high-priority row would take the batch slot its earlier low-priority
  group rows needed. The cost is that a later high-priority row waits one tick
  for the earlier rows of its group.
- **An abandoned partitioned row halts its key**, matching decision 6 (halt on
  poison) on the consumer side. Cleanup does not delete abandoned rows that
  have a partition key. An operator re-queues the row or marks it published
  to restart the key. Deleting it is unsafe when its event belongs to an
  event-sourced aggregate, because startup reconciliation can rebuild it as
  `pending` behind the key's later rows.
- **The processor publishes each group's rows in commit order within a batch.**
  When a row fails, the processor puts the group's later rows from that batch
  back to `pending` (`Outbox.release()`), without changing their retry counts.
- **No flag.** `sequential_by` has promised commit order since 0.17.0, and a
  flag that defaulted to the old behaviour would default to breaking that
  promise.

The hold-back is a parameter on the DAO claim contract (ADR-0013). PostgreSQL
applies it in the single claim statement. The other databases and the
in-memory adapter apply it in the portable guarded read-then-update path.

**Limits:**

- When `sequential_by` names a field that several aggregate instances carry,
  nothing serializes commits across those instances. A row with an earlier
  `created_at` can become visible after a later row of the same key has
  published.
- `created_at` comes from the writing host's clock. When clock skew between
  hosts is larger than the gap between two commits, the skew can swap the order
  of those commits.
- A row rebuilt by reconciliation gets the default priority, because the
  original priority is not stored with the event. With priority lanes on, the
  rebuilt row can be in the backfill lane while the key's other rows are in the
  primary lane. The two lanes are separate groups with no order between them,
  so the rebuilt row is ordered only against the key's other backfill rows.
- `specs/Outbox.tla` does not model the hold-back yet. `Outbox.release()`
  emits no trace record, the same as the backstop abandon.
