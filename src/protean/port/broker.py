import logging
from abc import ABCMeta, abstractmethod
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum, Flag, auto
from typing import TYPE_CHECKING, Any, NamedTuple, NotRequired, Protocol, TypedDict

from protean.exceptions import NotSupportedError, ProteanException

if TYPE_CHECKING:
    from protean.domain import Domain

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_DELAY = 1.0
BACKOFF_MULTIPLIER = 2.0
MESSAGE_TIMEOUT = 300.0
ENABLE_DLQ = True
OPERATION_STATE_TTL_MAX = 60.0


class LeaseLostError(ProteanException):
    """Raised when a fenced partition operation runs without holding the lease.

    Partition ownership is enforced with a lease and a fencing token (ADR-0028
    decision 5): every fenced read and ack checks, atomically, that the caller
    still holds the lease at its generation. A stalled-then-resumed owner whose
    lease has expired fails that check and gets this error instead of advancing
    or acking the partition. The partitioned consumer catches it and gives up
    the partition rather than treating it as a transient broker error.
    """


@dataclass
class DLQEntry:
    """A broker-agnostic view of one dead letter queue message.

    Attributes:
        dlq_id: Identifier within the DLQ (Redis stream ID or UUID).
        original_id: Original message identifier before it entered DLQ.
        stream: Original stream category the message belonged to.
        consumer_group: Consumer group that failed to process the message.
        payload: Full message payload dict.
        failure_reason: Why the message was moved to DLQ.
        failed_at: ISO 8601 timestamp of when the message failed.
        retry_count: Number of retries attempted before DLQ.
        dlq_stream: Name of the DLQ stream this entry lives in.
    """

    dlq_id: str
    original_id: str
    stream: str
    consumer_group: str
    payload: dict[str, Any]
    failure_reason: str
    failed_at: str | None
    retry_count: int
    dlq_stream: str


class OperationState(Enum):
    """Track the state of ack/nack operations for idempotency"""

    PENDING = "pending"
    ACKNOWLEDGED = "acknowledged"
    NACKED = "nacked"
    FAILED = "failed"


class BrokerCapabilities(Flag):
    # Tier 1: Universal Foundation (Every broker has these)
    PUBLISH = auto()  # Send messages
    SUBSCRIBE = auto()  # Receive messages

    # Tier 2: Storage & Consumer Management (Independent capabilities)
    CONSUMER_GROUPS = auto()  # Multiple consumers, load balancing

    # Tier 3: Message Lifecycle (Depends on CONSUMER_GROUPS)
    ACK_NACK = auto()  # Acknowledge successful/failed processing
    DELIVERY_GUARANTEES = auto()  # At-least-once delivery (depends on ACK_NACK)
    MESSAGE_ORDERING = auto()  # Preserve message order (can be independent)
    BLOCKING_READ = auto()  # Efficient blocking/waiting for new messages

    # Tier 4: Advanced Features (Various dependencies)
    DEAD_LETTER_QUEUE = auto()  # Handle failed messages (depends on ACK_NACK)
    REPLAY = auto()  # Re-read historical messages (depends on PERSISTENCE)
    STREAM_PARTITIONING = auto()  # Partition streams for scalability

    # Convenience Capability Sets
    BASIC_PUBSUB = PUBLISH | SUBSCRIBE

    SIMPLE_QUEUING = BASIC_PUBSUB | CONSUMER_GROUPS

    RELIABLE_MESSAGING = SIMPLE_QUEUING | ACK_NACK | DELIVERY_GUARANTEES

    ORDERED_MESSAGING = RELIABLE_MESSAGING | MESSAGE_ORDERING

    ENTERPRISE_STREAMING = (
        ORDERED_MESSAGING
        | DEAD_LETTER_QUEUE
        | REPLAY
        | STREAM_PARTITIONING
        | BLOCKING_READ
    )


class BrokerMessage(NamedTuple):
    """One message a broker returns from a read.

    Unpacks as ``(id, payload)``, like the tuples brokers returned before.
    """

    id: str
    payload: dict[str, Any]


class ConsumerInfo(TypedDict):
    """One consumer of a consumer group and the messages it has not acknowledged."""

    name: str
    pending: int


class ConsumerGroupInfo(TypedDict):
    """One consumer group, summed over the streams it reads.

    ``pending`` counts the messages delivered to the group and not yet
    acknowledged. A broker without acknowledgement reports ``0``.
    """

    name: str
    consumer_count: int
    pending: int
    consumers: NotRequired[list[ConsumerInfo]]
    last_delivered_id: NotRequired[str]
    created_at: NotRequired[float]


@dataclass(frozen=True)
class BrokerHealth:
    """The health record a broker reports.

    Attributes:
        healthy: ``False`` when the broker reports a problem.
        message_counts: Message counts, such as ``total_messages`` and
            ``in_flight``.
        consumer_groups: The consumer groups the broker knows, usually as
            ``count`` and ``names``.
        details: Adapter-specific data, such as server statistics, the
            broker's configuration, or an ``error`` or ``warning`` message.
    """

    healthy: bool
    message_counts: Mapping[str, int] = field(default_factory=dict)
    consumer_groups: Mapping[str, Any] = field(default_factory=dict)
    details: Mapping[str, Any] = field(default_factory=dict)


class BrokerPort(Protocol):
    """The operations a broker adapter implements.

    An adapter subclasses this Protocol explicitly. The ``Broker`` service in
    ``protean.infra.broker`` wraps the adapter and adds unit-of-work recording,
    the retry after a connection error, capability checks and synchronous
    dispatch to subscribers. Only the service calls these members.
    """

    name: str
    domain: "Domain"
    config: Mapping[str, Any]

    def __init__(
        self, name: str, domain: "Domain", config: Mapping[str, Any]
    ) -> None: ...

    @property
    @abstractmethod
    def capabilities(self) -> BrokerCapabilities:
        """Return the capabilities this broker supports."""

    @abstractmethod
    def ping(self) -> bool:
        """Return ``True`` when the broker responds, ``False`` otherwise."""

    @abstractmethod
    def health(self) -> BrokerHealth:
        """Return the broker's health record.

        Reports a failure in the record with ``healthy=False`` and does not
        raise.
        """

    @abstractmethod
    def get_connection(self) -> object:
        """Return the native client the broker holds, or ``None`` if it has none."""

    def close(self) -> None:
        """Close the broker and release its connections. No-op by default."""
        # A bare return keeps the default concrete: mypy treats a protocol
        # method whose body is only a docstring as abstract.
        return

    @abstractmethod
    def clear(self) -> None:
        """Remove every message and consumer group the broker holds.

        Meant for tests.
        """

    @abstractmethod
    def reconnect(self) -> bool:
        """Check the connection and reconnect if it is broken.

        Returns:
            ``True`` when the connection works, ``False`` when the broker
            cannot reconnect.
        """

    @abstractmethod
    def publish(self, stream: str, message: dict[str, Any]) -> str:
        """Send ``message`` to ``stream`` and return its identifier.

        Every broker returns a non-empty identifier. Its format is
        broker-specific.
        """

    @abstractmethod
    def read(
        self,
        stream: str,
        consumer_group: str,
        limit: int,
        *,
        new_messages: bool = False,
    ) -> list[BrokerMessage]:
        """Read up to ``limit`` messages from ``stream`` for ``consumer_group``.

        Creates the consumer group if it does not exist. With
        ``new_messages=True``, returns only messages no consumer in the group
        has received, and an empty list when only pending messages remain.
        """

    @abstractmethod
    def ack(self, stream: str, message_id: str, consumer_group: str) -> bool:
        """Acknowledge a message the group processed.

        Returns:
            ``True`` when the message was acknowledged, ``False`` otherwise.
        """

    @abstractmethod
    def nack(self, stream: str, message_id: str, consumer_group: str) -> bool:
        """Mark a message the group failed to process for redelivery.

        Returns:
            ``True`` when the message was marked, ``False`` otherwise.
        """

    @abstractmethod
    def create_group(self, stream: str, consumer_group: str) -> None:
        """Create ``consumer_group`` on ``stream`` if it does not exist."""

    @abstractmethod
    def consumer_groups(self) -> dict[str, ConsumerGroupInfo]:
        """Return the broker's consumer groups, keyed by group name."""

    def mark_subscription_owned(self, stream: str, consumer_group: str) -> None:
        """Record that a Protean subscription owns retries for this group.

        The subscription counts handler failures and publishes a message that
        runs out of retries to ``{stream}:dlq``. A broker that keeps its own
        limit on nacks stops dead-lettering the group's messages, and holds and
        redelivers them instead. The default does nothing, which is correct for
        a broker without such a limit.
        """
        # A bare return keeps the default concrete: mypy treats a protocol
        # method whose body is only a docstring as abstract.
        return

    def remove_stale_consumers(
        self, stream: str, consumer_group: str, current_consumer: str
    ) -> int:
        """Remove consumers an earlier run of this process left in the group.

        Returns:
            The number of consumers removed. The default removes none and
            returns ``0``.
        """
        return 0

    def reclaim_idle_pending(
        self,
        stream: str,
        consumer_group: str,
        consumer_name: str | None,
        min_idle_ms: int,
    ) -> dict[str, int]:
        """Move entries other consumers left pending to ``consumer_name``.

        Runs when a subscription starts. A broker that keeps a pending list per
        consumer takes over every entry of the group that has gone unread for
        at least ``min_idle_ms`` milliseconds. The claim does not deliver the
        entries: the subscription's next read of its own pending entries does.

        Args:
            consumer_name: The consumer to claim into. ``None`` means the
                consumer the broker's own ``read`` uses.

        Returns:
            The delivery count of each claimed entry, keyed by entry ID: how
            many times the group delivered it before the claim. The default
            claims nothing and returns ``{}``.
        """
        return {}


class BaseBroker(metaclass=ABCMeta):
    """Blocking reads, dead letters, partitions and trimming for broker adapters.

    A broker adapter subclasses this class and ``BrokerPort``, in that order.
    The core operations are on ``BrokerPort``. This class holds the optional
    groups of operations until they move into sub-protocols of the Port, and
    it is removed when they do.
    """

    if TYPE_CHECKING:
        # Port members that the wrappers below call. Each adapter defines them
        # through ``BrokerPort``.
        @property
        def capabilities(self) -> BrokerCapabilities: ...

        def read(
            self,
            stream: str,
            consumer_group: str,
            limit: int,
            *,
            new_messages: bool = False,
        ) -> list[BrokerMessage]: ...

        # Optional broker-specific method implemented by adapters that advertise
        # the BLOCKING_READ capability (e.g. the Redis Streams adapter). Declared
        # here for type-checkers so callers in this base class resolve; there is
        # no runtime attribute on BaseBroker itself.
        def _read_blocking(
            self,
            stream: str,
            consumer_group: str,
            consumer_name: str,
            timeout_ms: int = 5000,
            count: int = 1,
        ) -> list[tuple[str, dict[str, Any]]]: ...
        # Partition-per-key methods (ADR-0028), implemented only by brokers
        # advertising STREAM_PARTITIONING (the Redis Streams adapter). Declared
        # here so the capability-gated public wrappers below type-check; there is
        # no runtime attribute on BaseBroker itself.
        def _record_partition(self, category: str, key: str) -> None: ...

        def _partition_keys(self, category: str) -> set[str]: ...

        def _reap_partition(
            self,
            category: str,
            key: str,
            min_idle_ms: int,
            backfill_suffix: str | None,
        ) -> bool: ...

        def _acquire_partition_lease(
            self, lease_key: str, generation_key: str, owner_id: str, ttl_ms: int
        ) -> int | None: ...

        def _renew_partition_lease(
            self, lease_key: str, fence_token: str, ttl_ms: int
        ) -> bool: ...

        def _release_partition_lease(
            self, lease_key: str, fence_token: str
        ) -> bool: ...

        def _read_partition_fenced(
            self,
            stream: str,
            consumer_group: str,
            consumer_name: str,
            lease_key: str,
            fence_token: str,
            count: int,
            new_messages: bool,
        ) -> list[tuple[str, dict[str, Any]]]: ...

        def _ack_partition_fenced(
            self,
            stream: str,
            identifier: str,
            consumer_group: str,
            lease_key: str,
            fence_token: str,
        ) -> bool: ...

        def _reclaim_partition_pending(
            self,
            stream: str,
            consumer_group: str,
            consumer_name: str,
            min_idle_ms: int,
            count: int,
        ) -> list[tuple[str, dict[str, Any]]]: ...

    def __init__(self, name: str, domain: "Domain", config: Mapping[str, Any]) -> None:
        self.name = name
        self.domain = domain
        # A copy: the broker never writes to the configuration it was given.
        self.config: Mapping[str, Any] = dict(config)

    def read_blocking(
        self,
        stream: str,
        consumer_group: str,
        consumer_name: str,
        timeout_ms: int = 5000,
        count: int = 1,
    ) -> list[tuple[str, dict[str, Any]]]:
        """Read messages from the broker using blocking mode.

        This is an optional method that brokers can implement to support
        efficient blocking reads for stream-based subscriptions.

        Args:
            stream (str): The stream from which to read messages
            consumer_group (str): The consumer group identifier
            consumer_name (str): The unique consumer name within the group
            timeout_ms (int): Timeout in milliseconds to wait for messages (0 = return immediately, without waiting)
            count (int): Maximum number of messages to read

        Returns:
            list[tuple[str, dict]]: The list of (identifier, message) tuples
        """
        # Check if broker supports blocking reads
        if BrokerCapabilities.BLOCKING_READ not in self.capabilities:
            # Fall back to regular read for brokers that don't support blocking
            return list(self.read(stream, consumer_group, count))

        return self._read_blocking(
            stream, consumer_group, consumer_name, timeout_ms, count
        )

    def read_blocking_streams(
        self,
        streams: Sequence[str],
        consumer_group: str,
        consumer_name: str,
        timeout_ms: int = 5000,
        count: int = 1,
    ) -> dict[str, list[tuple[str, dict[str, Any]]]]:
        """Read messages from several streams in one call.

        The result has one key per requested stream, in the order given, with
        an empty list for a stream that returned nothing. An empty ``streams``
        returns an empty dict without reading. A broker without
        ``BLOCKING_READ`` reads each stream once without waiting. A broker
        changes how the streams are waited on by overriding
        ``_read_blocking_streams``.

        Args:
            streams: The streams to read from, in priority order.
            consumer_name: The consumer's name, unique within the group.
            timeout_ms: Longest time to wait for messages, in milliseconds.
                ``0`` returns immediately.
            count: Maximum number of messages to read from each stream.

        Returns:
            The ``(identifier, message)`` tuples read from each stream, keyed
            by stream name.
        """
        if not streams:
            return {}

        # Check if broker supports blocking reads
        if BrokerCapabilities.BLOCKING_READ not in self.capabilities:
            # Fall back to a regular read on each stream in turn
            return {
                stream: list(self.read(stream, consumer_group, count))
                for stream in streams
            }

        return self._read_blocking_streams(
            streams, consumer_group, consumer_name, timeout_ms, count
        )

    def _read_blocking_streams(
        self,
        streams: Sequence[str],
        consumer_group: str,
        consumer_name: str,
        timeout_ms: int = 5000,
        count: int = 1,
    ) -> dict[str, list[tuple[str, dict[str, Any]]]]:
        """Read several streams through ``_read_blocking``, one at a time.

        Every stream but the last is read without waiting, in order. The first
        one that returns messages ends the read. If all of them are empty, the
        last stream is read with the given ``timeout_ms``. Brokers that can wait
        on several streams in one call override this.
        """
        result: dict[str, list[tuple[str, dict[str, Any]]]] = {
            stream: [] for stream in streams
        }
        if not streams:
            return result

        *leading, last = streams
        for stream in leading:
            messages = self._read_blocking(
                stream, consumer_group, consumer_name, 0, count
            )
            if messages:
                result[stream] = messages
                return result

        result[last] = (
            self._read_blocking(last, consumer_group, consumer_name, timeout_ms, count)
            or []
        )
        return result

    # ------------------------------------------------------------------
    # Dead Letter Queue Management
    # ------------------------------------------------------------------

    def dlq_list(self, dlq_streams: list[str], limit: int = 100) -> list[DLQEntry]:
        """List DLQ messages across specified DLQ streams.

        Args:
            dlq_streams: List of DLQ stream names to query.
            limit: Maximum total messages to return.

        Returns:
            List of DLQEntry objects sorted by failure time (newest first).
        """
        if BrokerCapabilities.DEAD_LETTER_QUEUE not in self.capabilities:
            logger.warning(f"Broker {self.name} does not support DLQ management")
            return []
        return self._dlq_list(dlq_streams, limit)

    def dlq_inspect(self, dlq_stream: str, dlq_id: str) -> DLQEntry | None:
        """Inspect a specific DLQ message by its DLQ entry ID.

        Args:
            dlq_stream: The DLQ stream to look in.
            dlq_id: The entry identifier within the DLQ stream.

        Returns:
            DLQEntry if found, None otherwise.
        """
        if BrokerCapabilities.DEAD_LETTER_QUEUE not in self.capabilities:
            logger.warning(f"Broker {self.name} does not support DLQ management")
            return None
        return self._dlq_inspect(dlq_stream, dlq_id)

    def dlq_replay(self, dlq_stream: str, dlq_id: str, target_stream: str) -> bool:
        """Replay a single DLQ message back to its original stream.

        Args:
            dlq_stream: The DLQ stream the message is in.
            dlq_id: The entry identifier within the DLQ stream.
            target_stream: The stream to re-publish the message to.

        Returns:
            True if replayed successfully, False otherwise.
        """
        if BrokerCapabilities.DEAD_LETTER_QUEUE not in self.capabilities:
            logger.warning(f"Broker {self.name} does not support DLQ management")
            return False
        return self._dlq_replay(dlq_stream, dlq_id, target_stream)

    def dlq_replay_all(self, dlq_stream: str, target_stream: str) -> int:
        """Replay all DLQ messages from a stream back to the original stream.

        Args:
            dlq_stream: The DLQ stream to drain.
            target_stream: The stream to re-publish messages to.

        Returns:
            Number of messages replayed.
        """
        if BrokerCapabilities.DEAD_LETTER_QUEUE not in self.capabilities:
            logger.warning(f"Broker {self.name} does not support DLQ management")
            return 0
        return self._dlq_replay_all(dlq_stream, target_stream)

    def dlq_purge(self, dlq_stream: str) -> int:
        """Purge all messages from a DLQ stream.

        Args:
            dlq_stream: The DLQ stream to purge.

        Returns:
            Number of messages purged.
        """
        if BrokerCapabilities.DEAD_LETTER_QUEUE not in self.capabilities:
            logger.warning(f"Broker {self.name} does not support DLQ management")
            return 0
        return self._dlq_purge(dlq_stream)

    @abstractmethod
    def _dlq_list(self, dlq_streams: list[str], limit: int) -> list[DLQEntry]:
        """List DLQ messages across specified DLQ streams."""

    @abstractmethod
    def _dlq_inspect(self, dlq_stream: str, dlq_id: str) -> DLQEntry | None:
        """Inspect a specific DLQ message."""

    @abstractmethod
    def _dlq_replay(self, dlq_stream: str, dlq_id: str, target_stream: str) -> bool:
        """Replay a single DLQ message back to its original stream."""

    @abstractmethod
    def _dlq_replay_all(self, dlq_stream: str, target_stream: str) -> int:
        """Replay all DLQ messages from a stream."""

    @abstractmethod
    def _dlq_purge(self, dlq_stream: str) -> int:
        """Purge all messages from a DLQ stream."""

    # ------------------------------------------------------------------
    # DLQ Maintenance
    # ------------------------------------------------------------------

    def dlq_trim(self, dlq_stream: str, min_id: str) -> int:
        """Trim DLQ messages older than *min_id* (time-based trimming).

        This is an optional method used by the DLQ maintenance task to
        remove messages that have exceeded their retention period.
        Brokers that don't support time-based trimming can leave the
        default implementation which returns 0.

        Args:
            dlq_stream: The DLQ stream to trim.
            min_id: Cutoff identifier (format varies by broker).
                Messages older than this cutoff will be removed.

        Returns:
            Number of messages trimmed.
        """
        return 0

    def dlq_depth(self, dlq_stream: str) -> int:
        """Return the current number of messages in a DLQ stream.

        Brokers that don't support depth queries return 0.

        Args:
            dlq_stream: The DLQ stream to query.

        Returns:
            Number of messages in the DLQ stream.
        """
        return 0

    # ------------------------------------------------------------------
    # Stream Retention
    # ------------------------------------------------------------------

    def trim(self, stream: str, maxlen: int) -> int:
        """Trim a subscription stream to at most *maxlen* entries.

        Optional maintenance hook called after each processed batch when a
        subscription sets ``retention_maxlen``. Brokers with a persistent
        stream (e.g. Redis Streams) override this to cap the stream's size in a
        way that never removes an entry a consumer group still needs. Brokers
        without a persistent stream leave the default, which is a no-op.

        Args:
            stream: The stream to trim.
            maxlen: The target maximum number of entries to keep.

        Returns:
            Number of messages trimmed (0 by default).
        """
        return 0

    # ------------------------------------------------------------------
    # Partition-per-key support (ADR-0028)
    # ------------------------------------------------------------------
    # These back the partitioned stream consumer. Only a broker advertising
    # STREAM_PARTITIONING implements the underscore methods; the public wrappers
    # gate on that capability and raise ``NotSupportedError`` otherwise, so a
    # ``sequential_by`` handler can never silently run without its ordering
    # guarantee. They deliberately do not go through the service's retry after a
    # connection error: a fenced read/ack must fail loud on
    # a lost lease rather than be retried, and the partitioned consumer's poll
    # loop already backs off on transient broker errors.

    def _require_partitioning(self, operation: str) -> None:
        """Raise ``NotSupportedError`` if the broker cannot partition streams."""
        if BrokerCapabilities.STREAM_PARTITIONING not in self.capabilities:
            raise NotSupportedError(
                f"Broker {self.name} does not advertise STREAM_PARTITIONING, "
                f"required for `{operation}` (ADR-0028)."
            )

    def record_partition(self, category: str, key: str) -> None:
        """Record *key* in the maintained partition index for *category*.

        Called on publish to ``{category}:{key}`` so the partitioned consumer
        can discover the partition without scanning the keyspace (ADR-0028
        decision 7). Idempotent: recording the same key twice is a no-op.
        """
        self._require_partitioning("record_partition")
        self._record_partition(category, key)

    def partition_keys(self, category: str) -> set[str]:
        """Return the set of live partition keys recorded for *category*."""
        self._require_partitioning("partition_keys")
        return self._partition_keys(category)

    def reap_partition(
        self,
        category: str,
        key: str,
        min_idle_ms: int,
        backfill_suffix: str | None = None,
    ) -> bool:
        """Remove a drained, idle partition from the index and delete its streams.

        The check and the delete happen in one atomic step. The partition is
        reaped only when every consumer group on each of its streams has read
        and acknowledged every entry, and the newest entry on each stream is at
        least ``min_idle_ms`` old. An empty stream is always reaped. When priority lanes are enabled, pass
        ``backfill_suffix``: the backfill lane
        ``{category}:{key}:{backfill_suffix}`` is then checked and deleted with
        the main stream. The partition's generation counter is kept, so a
        partition created again under the same key keeps a rising generation.
        Call it from the partition's current owner once it has drained the
        partition. See ADR-0028 decision 7.

        Returns:
            ``True`` when the partition was reaped.

        Raises:
            NotSupportedError: The broker does not advertise
                ``STREAM_PARTITIONING``.
        """
        self._require_partitioning("reap_partition")
        return self._reap_partition(category, key, min_idle_ms, backfill_suffix)

    def acquire_partition_lease(
        self, lease_key: str, generation_key: str, owner_id: str, ttl_ms: int
    ) -> int | None:
        """Acquire the ownership lease for a partition, returning its generation.

        Atomically (ADR-0028 decision 5): if the lease is unheld, increment the
        durable generation counter, take the lease at that generation for
        *ttl_ms*, and return the generation. If already held, return ``None``.
        """
        self._require_partitioning("acquire_partition_lease")
        return self._acquire_partition_lease(
            lease_key, generation_key, owner_id, ttl_ms
        )

    def renew_partition_lease(
        self, lease_key: str, fence_token: str, ttl_ms: int
    ) -> bool:
        """Renew a held lease, extending its TTL. Returns ``False`` if lost.

        *fence_token* is ``{owner_id}:{generation}``. The renew succeeds only
        while the lease still holds that exact token, so an owner that lost the
        lease (expiry, takeover) cannot resurrect it.
        """
        self._require_partitioning("renew_partition_lease")
        return self._renew_partition_lease(lease_key, fence_token, ttl_ms)

    def release_partition_lease(self, lease_key: str, fence_token: str) -> bool:
        """Release a held lease on graceful shutdown. Returns ``False`` if not held."""
        self._require_partitioning("release_partition_lease")
        return self._release_partition_lease(lease_key, fence_token)

    def read_partition_fenced(
        self,
        stream: str,
        consumer_group: str,
        consumer_name: str,
        lease_key: str,
        fence_token: str,
        count: int = 1,
        new_messages: bool = True,
    ) -> list[tuple[str, dict[str, Any]]]:
        """Read from a partition stream, fenced by the ownership lease.

        The lease check and the ``XREADGROUP`` are one atomic step (ADR-0028
        decision 5): a caller that no longer holds the lease at *fence_token*
        reads nothing and raises `LeaseLostError` rather than advancing
        the partition. ``new_messages`` selects undelivered (``>``) vs this
        consumer's already-delivered pending (``0``) entries. Non-blocking.
        """
        self._require_partitioning("read_partition_fenced")
        return self._read_partition_fenced(
            stream,
            consumer_group,
            consumer_name,
            lease_key,
            fence_token,
            count,
            new_messages,
        )

    def ack_partition_fenced(
        self,
        stream: str,
        identifier: str,
        consumer_group: str,
        lease_key: str,
        fence_token: str,
    ) -> bool:
        """Ack a partition message, fenced by the ownership lease.

        Like [`read_partition_fenced`][protean.port.broker.BaseBroker.read_partition_fenced], the lease check and the ``XACK`` are
        atomic: a fenced stale owner cannot ack out from under the new owner and
        raises `LeaseLostError`.
        """
        self._require_partitioning("ack_partition_fenced")
        return self._ack_partition_fenced(
            stream, identifier, consumer_group, lease_key, fence_token
        )

    def reclaim_partition_pending(
        self,
        stream: str,
        consumer_group: str,
        consumer_name: str,
        min_idle_ms: int = 0,
        count: int = 100,
    ) -> list[tuple[str, dict[str, Any]]]:
        """Reclaim a dead owner's pending entries into *consumer_name* (XAUTOCLAIM).

        On failover the new owner reclaims the previous owner's unacked entries
        so none are lost or skipped (ADR-0028 decision 5, crash reclaim). Returns
        the reclaimed ``(id, payload)`` entries, now owned by *consumer_name*.
        """
        self._require_partitioning("reclaim_partition_pending")
        return self._reclaim_partition_pending(
            stream, consumer_group, consumer_name, min_idle_ms, count
        )
