"""Partition-per-key sequential stream consumer (ADR-0028).

``PartitionedStreamSubscription`` is the consumer side of ``sequential_by``. It
reads from every live partition stream of a category and processes each key's
events strictly in order, with a single active consumer per partition across
engine instances. The single-active-consumer guarantee is enforced by an
ownership *lease* plus a *fencing token*, not by a per-message lock (ADR-0028
decision 5), so a slow handler can never let two different same-key events run
concurrently or land out of order.

The moving parts:

- **Discovery** — each cycle the consumer reads the maintained partition index
  (``{category}:__partitions__``) written by the publisher; it never scans the
  keyspace (decision 7). New partitions are picked up with no restart.
- **Ownership** — for each discovered partition the consumer tries to take a
  lease (``acquire_partition_lease``). The lease carries a monotonically
  increasing *generation*; the owner's consumer name and every read/ack encode
  that generation, so a stalled-then-resumed owner whose lease expired is fenced
  out of both reading the next message and acking.
- **Per-partition workers** — each owned partition runs its own async task, so
  different keys are processed in parallel while one key stays strictly serial.
- **Crash reclaim** — on takeover the new owner reclaims the dead owner's
  pending entries (``XAUTOCLAIM``) so nothing is lost or skipped.
- **Halt on poison** — a partition that cannot process its head message halts
  (no auto-DLQ, no advance past the poison), scoped to that one partition
  (decision 6). Unwedging is an explicit operator action.
- **Cold-partition retirement** — the owner reaps a partition that has drained
  and gone idle, keeping the index bounded (decision 7).

Process managers partition by correlation value across their subscribed
categories: one instance leases a correlation value and is the sole processor of
every category's partition for it (decision 2). That is modelled here as a
partition "unit" spanning several physical streams under one lease.
"""

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Any

from protean.core.command_handler import BaseCommandHandler
from protean.core.event_handler import BaseEventHandler
from protean.port.broker import LeaseLostError
from protean.utils.eventing import Message
from protean.utils.telemetry import get_domain_metrics

from .stream_subscription import StreamSubscription

if TYPE_CHECKING:
    from protean.server.engine import Engine

    from .profiles import SubscriptionConfig

logger = logging.getLogger(__name__)

# Internal key suffixes for the ownership lease and its generation counter.
# Both are reserved ``__name__`` sentinels a partition key can never equal
# (rejected at record creation), so they never collide with a partition stream.
LEASE_SUFFIX = "__lease__"
GENERATION_SUFFIX = "__generation__"


class _OwnedPartition:
    """Runtime state for one partition this instance currently owns.

    A "partition" is a single stream for an event/command handler, or a set of
    streams sharing one correlation value for a process manager. ``partition_id``
    is the partition key (handlers) or the correlation value (process managers).
    """

    __slots__ = (
        "consumer_name",
        "fence_token",
        "generation",
        "halted",
        "lease_key",
        "partition_id",
        "retry_counts",
        "streams",
        "task",
    )

    def __init__(
        self,
        partition_id: str,
        streams: list[tuple[str, str]],
        lease_key: str,
        generation: int,
        fence_token: str,
    ) -> None:
        self.partition_id = partition_id
        # (category, physical_stream) pairs — one for a handler, several for a PM.
        self.streams = streams
        self.lease_key = lease_key
        self.generation = generation
        # The fence token doubles as the Redis consumer name so each generation
        # owns its own pending-entries list; a new generation reclaims the old.
        self.fence_token = fence_token
        self.consumer_name = fence_token
        self.task: asyncio.Task[None] | None = None
        self.halted = False
        self.retry_counts: dict[str, int] = {}


class PartitionedStreamSubscription(StreamSubscription):
    """A stream subscription that owns and serially drains per-key partitions.

    Constructed by :class:`~protean.server.subscription.factory.SubscriptionFactory`
    for any handler on a partitioned category (a category that some handler
    declares ``sequential_by`` on). See the module docstring for the design.
    """

    def __init__(
        self,
        engine: "Engine",
        stream_category: str,
        handler: type[BaseEventHandler | BaseCommandHandler],
        stream_categories: list[str] | None = None,
        correlated: bool = False,
        messages_per_tick: int | None = None,
        blocking_timeout_ms: int | None = None,
        max_retries: int | None = None,
        retry_delay_seconds: float | None = None,
        enable_dlq: bool | None = None,
    ) -> None:
        super().__init__(
            engine,
            stream_category,
            handler,
            messages_per_tick=messages_per_tick,
            blocking_timeout_ms=blocking_timeout_ms,
            max_retries=max_retries,
            retry_delay_seconds=retry_delay_seconds,
            enable_dlq=enable_dlq,
        )

        # A handler owns one category; a ``sequential_by`` process manager owns
        # several and leases by correlation value spanning them (ADR-0028 #2).
        self._categories = stream_categories or [stream_category]
        self._correlated = correlated

        server_config = engine.domain.config.get("server", {})
        part_config = server_config.get("partitioning", {})
        # Lease TTL and heartbeat cadence. The heartbeat must fire several times
        # per TTL so a live owner never lets its lease lapse; the default keeps a
        # ~5x margin. Shorter TTL = faster failover but more reclaim churn.
        self.lease_ttl_ms: int = int(part_config.get("lease_ttl_ms", 15000))
        self.heartbeat_interval: float = float(
            part_config.get("heartbeat_interval_seconds", self.lease_ttl_ms / 5000)
        )
        # How long a per-partition worker waits between empty reads.
        self.poll_interval: float = float(
            part_config.get("poll_interval_seconds", 0.25)
        )
        # A partition drained and idle for this long is retired (index pruned).
        self.reap_idle_ms: int = int(part_config.get("reap_idle_ms", 3_600_000))

        # Unique per engine instance — this is the lease owner identity.
        self.owner_id = self.subscription_id

        # partition_id -> owned-partition state for partitions we currently hold.
        self._owned: dict[str, _OwnedPartition] = {}

        # When False, ``_acquire_new`` records ownership without spawning a
        # worker task, so tests can drive draining deterministically. Production
        # leaves it True so each owned partition runs its own loop.
        self._auto_workers = True

    @classmethod
    def from_partitioned_config(
        cls,
        engine: "Engine",
        stream_category: str,
        handler: type[BaseEventHandler | BaseCommandHandler],
        config: "SubscriptionConfig",
        stream_categories: list[str] | None = None,
        correlated: bool = False,
    ) -> "PartitionedStreamSubscription":
        """Build a partitioned subscription from a resolved config.

        A dedicated constructor (rather than overriding ``from_config``) because
        it needs the partition-specific ``stream_categories`` and ``correlated``
        inputs the base signature does not carry.
        """
        return cls(
            engine=engine,
            stream_category=stream_category,
            handler=handler,
            stream_categories=stream_categories,
            correlated=correlated,
            messages_per_tick=config.messages_per_tick,
            blocking_timeout_ms=config.blocking_timeout_ms,
            max_retries=config.max_retries,
            retry_delay_seconds=config.retry_delay_seconds,
            enable_dlq=config.enable_dlq,
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        """Bind the broker; partition groups are created lazily per partition.

        Unlike the base subscription this does not create a consumer group on the
        base category stream — a partitioned category's events are published to
        ``{category}:{key}`` streams, so the base stream stays empty and a group
        there would be misleading. Each partition's group is ensured on demand
        when the owner first reads or reclaims it.
        """
        self.broker = self.engine.domain.brokers.get("default")
        if not self.broker:
            raise RuntimeError(
                f"No default broker configured for "
                f"PartitionedStreamSubscription {self.subscriber_name}"
            )
        logger.debug(
            "partition.initialized",
            extra={
                "subscriber": self.subscriber_name,
                "categories": self._categories,
                "correlated": self._correlated,
            },
        )

    async def poll(self) -> None:
        """Discovery + heartbeat loop.

        Each cycle renews the leases we hold, discovers partitions from the
        index, and takes leases on any we do not yet own (spawning a worker per
        newly-owned partition). Per-partition draining happens in those worker
        tasks, so different keys drain in parallel. Runs until shutdown.
        """
        consecutive_errors = 0
        while self.keep_going and not self.engine.shutting_down:
            try:
                await self._discovery_pass()
                consecutive_errors = 0
                await asyncio.sleep(self.heartbeat_interval)
            except asyncio.CancelledError:
                logger.info(
                    "partition.discovery_cancelled",
                    extra={"subscriber": self.subscriber_name},
                )
                break
            except Exception:
                consecutive_errors += 1
                logger.exception(
                    "partition.discovery_error",
                    extra={
                        "subscriber": self.subscriber_name,
                        "attempt": consecutive_errors,
                    },
                )
                backoff = min(2 ** (consecutive_errors - 1), 30)
                await asyncio.sleep(backoff)

    async def cleanup(self) -> None:
        """Cancel worker tasks and release held leases on shutdown."""
        for owned in list(self._owned.values()):
            if owned.task is not None:
                owned.task.cancel()
        for owned in list(self._owned.values()):
            await self._release_lease(owned)
        self._owned.clear()
        await super().cleanup()

    # ------------------------------------------------------------------
    # Discovery, ownership, heartbeat
    # ------------------------------------------------------------------

    async def _discovery_pass(self) -> None:
        """Run one discovery + heartbeat iteration (renew, discover, acquire)."""
        await self._renew_owned()
        units = await asyncio.to_thread(self._discover_units)
        await self._acquire_new(units)

    def _discover_units(self) -> dict[str, list[tuple[str, str]]]:
        """Return ``partition_id -> [(category, physical_stream), ...]`` from the index.

        For a handler this is one entry per key on its single category. For a
        process manager it unions the index across every subscribed category and
        groups by correlation value, so one unit spans that value's streams
        across categories (ADR-0028 decision 2).
        """
        assert self.broker is not None, "Broker not initialized"
        units: dict[str, list[tuple[str, str]]] = {}
        for category in self._categories:
            try:
                keys = self.broker.partition_keys(category)
            except Exception:
                logger.exception(
                    "partition.discovery_read_failed",
                    extra={"category": category},
                )
                continue
            for key in keys:
                units.setdefault(key, []).append((category, f"{category}:{key}"))
        return units

    async def _renew_owned(self) -> None:
        """Renew every held lease; drop ownership of any we have lost."""
        assert self.broker is not None, "Broker not initialized"
        for partition_id, owned in list(self._owned.items()):
            renewed = await asyncio.to_thread(
                self.broker.renew_partition_lease,
                owned.lease_key,
                owned.fence_token,
                self.lease_ttl_ms,
            )
            if not renewed:
                logger.warning(
                    "partition.lease_renew_failed",
                    extra={
                        "subscriber": self.subscriber_name,
                        "partition": partition_id,
                    },
                )
                await self._drop_owned(partition_id)

    async def _acquire_new(self, units: dict[str, list[tuple[str, str]]]) -> None:
        """Take leases on discovered partitions we do not yet own."""
        assert self.broker is not None, "Broker not initialized"
        for partition_id, streams in units.items():
            if partition_id in self._owned:
                # Already owned. A partition unit can grow — a process manager's
                # correlation value gains a new category stream when a later
                # event type for it is first published — so fold any newly
                # discovered streams into the owned unit rather than skipping it,
                # or the owner would never read the late-arriving stream.
                self._merge_streams(self._owned[partition_id], streams)
                continue
            lease_key = self._lease_key(partition_id)
            generation_key = self._generation_key(partition_id)
            generation = await asyncio.to_thread(
                self.broker.acquire_partition_lease,
                lease_key,
                generation_key,
                self.owner_id,
                self.lease_ttl_ms,
            )
            if generation is None:
                continue  # owned by another instance
            fence_token = f"{self.owner_id}:{generation}"
            owned = _OwnedPartition(
                partition_id,
                streams,
                lease_key,
                generation,
                fence_token,
            )
            self._owned[partition_id] = owned
            logger.info(
                "partition.acquired",
                extra={
                    "subscriber": self.subscriber_name,
                    "partition": partition_id,
                    "generation": generation,
                },
            )
            if self._auto_workers:
                # Runs on the loop driving ``poll`` (the engine loop in
                # production, the test loop under pytest).
                owned.task = asyncio.create_task(self._run_partition(owned))

    def _lease_key(self, partition_id: str) -> str:
        """Lease key for a partition, namespaced by consumer group.

        Namespacing by the consumer group (the handler FQN) rather than the raw
        stream lets two different handlers on the same partitioned category each
        own the partition independently. Neither the group (a dotted FQN) nor the
        partition id (colons rejected at record creation) contains a colon, so
        this composes unambiguously.
        """
        return f"{self.consumer_group}:{partition_id}:{LEASE_SUFFIX}"

    def _generation_key(self, partition_id: str) -> str:
        """Durable generation counter key for a partition (see :meth:`_lease_key`)."""
        return f"{self.consumer_group}:{partition_id}:{GENERATION_SUFFIX}"

    @staticmethod
    def _merge_streams(
        owned: _OwnedPartition, discovered: list[tuple[str, str]]
    ) -> None:
        """Add newly-discovered streams to an already-owned unit, preserving order.

        A process manager unit keyed by a correlation value spans one stream per
        subscribed category, but those streams appear as each event type is first
        published for that value — so the unit must absorb late arrivals rather
        than freeze the stream list it was created with.
        """
        existing = {stream for _category, stream in owned.streams}
        for category, stream in discovered:
            if stream not in existing:
                owned.streams.append((category, stream))
                existing.add(stream)

    async def _drop_owned(self, partition_id: str) -> None:
        """Give up local ownership of a partition (cancel its worker)."""
        owned = self._owned.pop(partition_id, None)
        if owned is None:
            return
        if owned.task is not None and owned.task is not asyncio.current_task():
            owned.task.cancel()

    async def _release_lease(self, owned: _OwnedPartition) -> None:
        """Best-effort release of a held lease (graceful handoff)."""
        assert self.broker is not None, "Broker not initialized"
        try:
            await asyncio.to_thread(
                self.broker.release_partition_lease,
                owned.lease_key,
                owned.fence_token,
            )
        except Exception:
            logger.debug(
                "partition.lease_release_failed",
                extra={"partition": owned.partition_id},
            )

    # ------------------------------------------------------------------
    # Per-partition draining
    # ------------------------------------------------------------------

    async def _run_partition(self, owned: _OwnedPartition) -> None:
        """Own one partition: reclaim, then drain it strictly in order until idle.

        Exits when the partition is retired (drained + idle), the lease is lost
        (fenced out), the partition halts on poison, or the engine shuts down.
        The discovery/heartbeat loop keeps the lease alive while this runs.
        """
        idle_since: float | None = None
        try:
            await self._reclaim(owned)
            while (
                self.keep_going
                and not self.engine.shutting_down
                and not owned.halted
                and owned.partition_id in self._owned
            ):
                processed = await self._drain_once(owned)
                if processed > 0:
                    idle_since = None
                    continue
                now = time.monotonic()
                if idle_since is None:
                    idle_since = now
                elif (now - idle_since) * 1000 >= self.reap_idle_ms:
                    if await self._retire(owned):
                        return
                    idle_since = None
                await asyncio.sleep(self.poll_interval)
        except asyncio.CancelledError:
            raise
        except LeaseLostError:
            logger.info(
                "partition.fenced_out",
                extra={
                    "subscriber": self.subscriber_name,
                    "partition": owned.partition_id,
                },
            )
            await self._drop_owned(owned.partition_id)
        except Exception:
            # A transient broker error (connection blip, reclaim failure) must
            # not silently wedge the partition: give up local ownership so the
            # lease lapses and this instance (or another) re-acquires it and
            # retries, rather than renewing a lease for a dead worker forever.
            logger.exception(
                "partition.worker_error",
                extra={
                    "subscriber": self.subscriber_name,
                    "partition": owned.partition_id,
                },
            )
            await self._drop_owned(owned.partition_id)

    async def _reclaim(self, owned: _OwnedPartition) -> None:
        """Reclaim a dead owner's pending entries into this generation (XAUTOCLAIM).

        Reassigns any pending entries left by a previous owner to this owner's
        consumer name so they are re-read and re-processed in order, not lost.
        The entries themselves are picked up by the pending-first read in
        :meth:`_drain_once`; here we only need to move ownership of them.

        Reclaim is a correctness precondition, not best-effort: if it fails, the
        new owner must not go on to drain new messages ahead of the un-reclaimed
        old pending entries (that would reorder the key). So a broker error is
        left to propagate to :meth:`_run_partition`, which drops ownership and
        lets the lease re-cycle so reclaim is retried cleanly.
        """
        assert self.broker is not None, "Broker not initialized"
        for _category, stream in owned.streams:
            lanes = [stream]
            if self._lanes_enabled:
                lanes.append(self._backfill_stream(stream))
            for lane in lanes:
                await asyncio.to_thread(
                    self.broker.reclaim_partition_pending,
                    lane,
                    self.consumer_group,
                    owned.consumer_name,
                )

    def _backfill_stream(self, primary: str) -> str:
        """The backfill-lane stream name for a primary partition stream."""
        return f"{primary}:{self._backfill_suffix}"

    async def _drain_once(self, owned: _OwnedPartition) -> int:
        """Process at most one message per stream in the unit, strictly in order.

        Reads this consumer's pending entries first (retries and reclaimed
        entries) before any new message, so the head is never skipped. When
        priority lanes are enabled a key also has a backfill lane, drained only
        when its primary lane is empty (production before backfill, as elsewhere),
        so backfill-routed partitioned events are consumed, not stranded. On a
        processing failure it stops advancing that stream — the failed message
        stays pending as the head — and either schedules a retry or halts the
        partition once retries are exhausted (ADR-0028 decision 6). Returns the
        number of messages successfully processed this pass.
        """
        assert self.broker is not None, "Broker not initialized"
        processed = 0
        for category, stream in owned.streams:
            if owned.halted:
                break
            head = await self._read_head(owned, stream)
            if head is None and self._lanes_enabled:
                head = await self._read_head(owned, self._backfill_stream(stream))
            if head is None:
                continue
            physical_stream, identifier, payload = head
            succeeded = await self._process_message(
                owned, category, physical_stream, identifier, payload
            )
            if succeeded:
                processed += 1
            else:
                # Do NOT advance past a failed head — that would reorder the key.
                await self._on_failure(owned, physical_stream, identifier)
        return processed

    async def _read_head(
        self, owned: _OwnedPartition, stream: str
    ) -> tuple[str, str, dict[str, Any]] | None:
        """Fenced-read the head of *stream* (pending before new), or ``None``.

        Two reads are inherent — XREADGROUP cannot ask for "0 then >" in one call.
        Returns ``(stream, identifier, payload)`` so the caller acks and tracks
        retries against the exact physical stream (primary or backfill lane).
        """
        assert self.broker is not None, "Broker not initialized"
        for new_messages in (False, True):  # pending first, then new
            messages = await asyncio.to_thread(
                self.broker.read_partition_fenced,
                stream,
                self.consumer_group,
                owned.consumer_name,
                owned.lease_key,
                owned.fence_token,
                count=1,
                new_messages=new_messages,
            )
            if messages:
                identifier, payload = messages[0]
                return stream, identifier, payload
        return None

    async def _process_message(
        self,
        owned: _OwnedPartition,
        category: str,
        stream: str,
        identifier: str,
        payload: dict[str, Any],
    ) -> bool:
        """Deserialize, handle, and fenced-ack a single partition message.

        A deserialization failure is treated as a processing failure (the caller
        retries then halts) rather than routed to a DLQ: auto-DLQ would advance
        the partition past the poison head and reorder the key.
        """
        assert self.broker is not None, "Broker not initialized"
        try:
            message = Message.deserialize(payload)
        except Exception:
            logger.error(
                "partition.deserialize_failed",
                extra={"partition": owned.partition_id, "message_id": identifier},
            )
            return False

        metrics = get_domain_metrics(self.engine.domain)
        attrs = {
            "subscription": self.subscriber_class_name,
            "handler": self.subscriber_class_name,
            "stream": stream,
        }
        start = time.monotonic()
        is_successful = await self.engine.handle_message(
            self.handler, message, worker_id=owned.consumer_name
        )
        metrics.subscription_processing_duration.record(time.monotonic() - start, attrs)
        metrics.subscription_messages_processed.add(
            1, {**attrs, "status": "ok" if is_successful else "error"}
        )

        if not is_successful:
            return False

        # Fenced ack: raises LeaseLostError (propagated to stop the worker) if we
        # no longer hold the lease, so a fenced stale owner cannot ack.
        acked = await asyncio.to_thread(
            self.broker.ack_partition_fenced,
            stream,
            identifier,
            self.consumer_group,
            owned.lease_key,
            owned.fence_token,
        )
        if acked:
            owned.retry_counts.pop(f"{stream}:{identifier}", None)
        else:
            # We held the lease (no LeaseLostError) yet XACK removed nothing —
            # the entry left this consumer's pending list unexpectedly. The
            # handler already ran, so we still count it processed, but surface
            # the anomaly rather than hiding it.
            logger.warning(
                "partition.ack_noop",
                extra={"partition": owned.partition_id, "message_id": identifier},
            )
        return True

    async def _on_failure(
        self, owned: _OwnedPartition, stream: str, identifier: str
    ) -> None:
        """Retry a failed head message, or halt the partition once exhausted.

        The message stays pending (Redis keeps unacked entries), so a retry
        re-reads the same head. After ``max_retries`` the partition halts: it
        stops advancing and leaves the poison as the pending head for an operator
        to resolve. The halt is scoped to this partition; others keep flowing.
        """
        # Key the retry count by the physical stream too: a primary and a backfill
        # lane can hand out the same Redis id, and they must not share a counter.
        retry_key = f"{stream}:{identifier}"
        count = owned.retry_counts.get(retry_key, 0) + 1
        owned.retry_counts[retry_key] = count
        if count < self.max_retries:
            logger.warning(
                "partition.retry",
                extra={
                    "subscriber": self.subscriber_name,
                    "partition": owned.partition_id,
                    "message_id": identifier,
                    "attempt": count,
                    "max_retries": self.max_retries,
                },
            )
            await asyncio.sleep(self.retry_delay_seconds)
        else:
            owned.halted = True
            logger.error(
                "partition.halted_on_poison",
                extra={
                    "subscriber": self.subscriber_name,
                    "partition": owned.partition_id,
                    "stream": stream,
                    "message_id": identifier,
                    "max_retries": self.max_retries,
                },
            )

    async def _retire(self, owned: _OwnedPartition) -> bool:
        """Reap a drained, idle partition and release its lease.

        Only the owner retires a partition, and only once it has fully drained
        it, so no in-flight work is dropped. The broker's reap is itself guarded
        (no pending in any group, stream idle for ``reap_idle_ms``), so a partition
        that quietly received new work is not reaped out from under it. Returns
        ``True`` when every stream in the unit was reaped and the lease released.
        """
        assert self.broker is not None, "Broker not initialized"
        # When lanes are on, reap covers the backfill lane too, so a key with
        # unconsumed backfill work is never dropped from the index.
        backfill_suffix = self._backfill_suffix if self._lanes_enabled else None
        all_reaped = True
        for category, _stream in owned.streams:
            try:
                reaped = await asyncio.to_thread(
                    self.broker.reap_partition,
                    category,
                    owned.partition_id,
                    self.reap_idle_ms,
                    backfill_suffix,
                )
            except Exception:
                logger.exception(
                    "partition.reap_failed",
                    extra={"partition": owned.partition_id, "category": category},
                )
                reaped = False
            all_reaped = all_reaped and reaped
        if not all_reaped:
            return False
        await self._release_lease(owned)
        self._owned.pop(owned.partition_id, None)
        logger.info(
            "partition.retired",
            extra={
                "subscriber": self.subscriber_name,
                "partition": owned.partition_id,
            },
        )
        return True


__all__ = ["PartitionedStreamSubscription"]
