import logging
from abc import ABCMeta, abstractmethod
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum, Flag, auto
from typing import (
    TYPE_CHECKING,
    Any,
    ClassVar,
    NamedTuple,
    NotRequired,
    Protocol,
    TypedDict,
)

from protean.exceptions import ProteanException

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
    STREAM_RETENTION = auto()  # Trim a stream to bound its size

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
        | STREAM_RETENTION
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

    ``pending`` is the broker's own count of messages delivered to the group
    and not yet settled, so it differs between brokers. The inline broker
    counts messages delivered and not yet acknowledged or nacked. The Redis
    broker reports the length of the Redis pending list, which keeps a nacked
    message. A broker without acknowledgement reports ``0``.

    ``consumer_count`` counts the consumers the broker tracks. The inline
    broker tracks none and reports ``0``.
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

    An adapter subclasses this Protocol explicitly, and also subclasses
    ``BaseBroker``, which holds the dead-letter queue. The ``Broker`` service
    raises ``NotSupportedError`` for those operations on an adapter that is
    not a ``BaseBroker``. An adapter that declares a flag listed in
    `CAPABILITY_PORTS` subclasses the sub-protocol the flag maps to, such as
    ``BlockingReadPort`` for ``BrokerCapabilities.BLOCKING_READ``. Each
    sub-protocol extends ``BrokerPort``.

    The ``Broker`` service in ``protean.infra.broker`` wraps the adapter and
    adds unit-of-work recording, the retry after a connection error,
    capability checks and synchronous dispatch to subscribers. Code outside
    the adapter calls these members through the service. The adapter's own
    methods may call them directly.
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
        ``new_messages=True``, skips messages that are pending in the group
        (delivered and not acknowledged), and returns an empty list when only
        pending messages remain. A broker that redelivers a nacked message by
        putting it back on the stream returns it as a new message.
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


class BlockingReadPort(BrokerPort, Protocol):
    """The blocking reads of a broker that declares ``BLOCKING_READ``.

    A broker that declares ``BrokerCapabilities.BLOCKING_READ`` subclasses this
    Protocol and implements both members. The ``Broker`` service calls them
    when the broker declares the flag, and reads each stream once with
    ``read`` when it does not.
    """

    @abstractmethod
    def read_blocking(
        self,
        stream: str,
        consumer_group: str,
        consumer_name: str,
        timeout_ms: int = 5000,
        limit: int = 1,
    ) -> list[BrokerMessage]:
        """Read up to ``limit`` messages from ``stream`` for one consumer.

        Waits up to ``timeout_ms`` milliseconds for a message.
        ``timeout_ms=0`` returns at once. Returns an empty list when no
        message arrives in time.
        """

    @abstractmethod
    def read_blocking_streams(
        self,
        streams: Sequence[str],
        consumer_group: str,
        consumer_name: str,
        timeout_ms: int = 5000,
        limit: int = 1,
    ) -> dict[str, list[BrokerMessage]]:
        """Read several streams for one consumer, waiting on all of them at once.

        Waits up to ``timeout_ms`` milliseconds in total for a message on any
        of ``streams``. ``timeout_ms=0`` returns at once. ``limit`` caps the
        messages read from each stream.

        Returns:
            The messages read from each stream, keyed by stream name in the
            order given. Every requested stream has a key, with an empty list
            when it returned nothing. An empty ``streams`` returns ``{}``.
        """


class PartitioningPort(BrokerPort, Protocol):
    """The partition-per-key operations of a broker that declares ``STREAM_PARTITIONING``.

    These back the partitioned stream consumer (ADR-0028). A broker that
    declares ``BrokerCapabilities.STREAM_PARTITIONING`` subclasses this
    Protocol and implements every member. The ``Broker`` service raises
    ``NotSupportedError`` for each of them on a broker without the flag.
    """

    @abstractmethod
    def record_partition(self, category: str, key: str) -> None:
        """Record ``key`` in the partition index for ``category``.

        Called on publish to ``{category}:{key}`` so the partitioned consumer
        can find the partition without scanning the keyspace (ADR-0028
        decision 7). Recording the same key twice changes nothing.
        """

    @abstractmethod
    def partition_keys(self, category: str) -> set[str]:
        """Return the live partition keys recorded for ``category``."""

    @abstractmethod
    def reap_partition(
        self,
        category: str,
        key: str,
        min_idle_ms: int,
        backfill_suffix: str | None,
    ) -> bool:
        """Remove a drained, idle partition from the index and delete its streams.

        The check and the delete happen in one atomic step. A stream that
        holds entries passes the check only when it has at least one consumer
        group, every group on it has read and acknowledged every entry, and
        its newest entry is at least ``min_idle_ms`` old. An empty stream
        always passes. The partition is reaped only when each of its streams
        passes. When priority lanes are enabled, ``backfill_suffix`` names the
        backfill lane ``{category}:{key}:{backfill_suffix}``, which is checked
        and deleted with the main stream, so a backfill lane with unread
        entries keeps an empty main stream from being reaped. The partition's generation counter is
        kept, so a partition created again under the same key keeps a rising
        generation. The partition's current owner calls it once it has
        drained the partition. See ADR-0028 decision 7.

        Returns:
            ``True`` when the partition was reaped.
        """

    @abstractmethod
    def acquire_partition_lease(
        self, lease_key: str, generation_key: str, owner_id: str, ttl_ms: int
    ) -> int | None:
        """Acquire the ownership lease for a partition and return its generation.

        In one atomic step (ADR-0028 decision 5): when the lease is unheld,
        increments the durable generation counter, takes the lease at that
        generation for ``ttl_ms`` milliseconds, and returns the generation.
        Returns ``None`` when the lease is already held.
        """

    @abstractmethod
    def renew_partition_lease(
        self, lease_key: str, fence_token: str, ttl_ms: int
    ) -> bool:
        """Renew a held lease so that it expires ``ttl_ms`` milliseconds from now.

        ``fence_token`` is ``{owner_id}:{generation}``. The renew succeeds only
        while the lease still holds that exact token, so an owner that lost
        the lease to expiry or a takeover cannot take it back.

        Returns:
            ``False`` when the lease is lost.
        """

    @abstractmethod
    def release_partition_lease(self, lease_key: str, fence_token: str) -> bool:
        """Release a held lease on graceful shutdown.

        Returns:
            ``False`` when the lease is not held at ``fence_token``.
        """

    @abstractmethod
    def read_partition_fenced(
        self,
        stream: str,
        consumer_group: str,
        consumer_name: str,
        lease_key: str,
        fence_token: str,
        limit: int,
        new_messages: bool,
    ) -> list[BrokerMessage]:
        """Read up to ``limit`` messages from a partition stream, fenced by the lease.

        The lease check and the read are one atomic step (ADR-0028 decision
        5). A caller that no longer holds the lease at ``fence_token`` gets
        ``LeaseLostError`` and reads no message. ``new_messages=True`` reads undelivered entries, and
        ``new_messages=False`` reads the entries already delivered to this
        consumer and not acknowledged. Does not wait for messages.

        Raises:
            LeaseLostError: The caller does not hold the lease at
                ``fence_token``.
        """

    @abstractmethod
    def ack_partition_fenced(
        self,
        stream: str,
        message_id: str,
        consumer_group: str,
        lease_key: str,
        fence_token: str,
    ) -> bool:
        """Acknowledge a partition message, fenced by the lease.

        The lease check and the acknowledgement are one atomic step, so an
        owner whose lease was taken over cannot acknowledge a message the new
        owner holds.

        Returns:
            ``True`` when the message was acknowledged.

        Raises:
            LeaseLostError: The caller does not hold the lease at
                ``fence_token``.
        """

    @abstractmethod
    def reclaim_partition_pending(
        self,
        stream: str,
        consumer_group: str,
        consumer_name: str,
        min_idle_ms: int,
        limit: int,
    ) -> list[BrokerMessage]:
        """Move a dead owner's pending entries to ``consumer_name``.

        On failover the new owner reclaims the previous owner's unacknowledged
        entries so none are lost or skipped (ADR-0028 decision 5). Claims
        entries idle for at least ``min_idle_ms`` milliseconds, ``limit`` per
        page, and stops at the end of the pending list or at the first page
        that claims nothing.

        Returns:
            The reclaimed messages, now pending on ``consumer_name``. A claimed
            entry whose payload was already trimmed from the stream is left
            out.
        """


class StreamRetentionPort(BrokerPort, Protocol):
    """Stream trimming for a broker that declares ``STREAM_RETENTION``.

    A broker that declares ``BrokerCapabilities.STREAM_RETENTION`` subclasses
    this Protocol and implements ``trim``. The ``Broker`` service trims
    nothing on a broker without the flag.
    """

    @abstractmethod
    def trim(self, stream: str) -> int:
        """Remove the entries of ``stream`` that every consumer group has acknowledged.

        The stream subscription calls it after each processed batch. The trim
        removes only entries that every consumer group on ``stream`` has read
        and acknowledged, so no group loses a message it still needs. It need
        not remove all of them.

        Returns:
            The number of entries removed.
        """


CAPABILITY_PORTS: dict[BrokerCapabilities, type[object]] = {
    BrokerCapabilities.BLOCKING_READ: BlockingReadPort,
    BrokerCapabilities.STREAM_PARTITIONING: PartitioningPort,
    BrokerCapabilities.STREAM_RETENTION: StreamRetentionPort,
}
"""The sub-protocol an adapter subclasses when it declares each flag listed.

Typed `type[object]` because mypy in strict mode rejects a Protocol with
abstract members where `type[BrokerPort]` is expected.
"""


class BaseBroker(metaclass=ABCMeta):
    """Dead letters for broker adapters.

    A broker adapter subclasses this class and ``BrokerPort``, in that order.
    The core operations are on ``BrokerPort``. This class holds the
    dead-letter operations until they move into a sub-protocol of the Port,
    and it is removed when they do.

    Each adapter sets ``broker_type`` to the name it is known by, such as
    ``"inline"``, ``"redis"`` or ``"redis_pubsub"``.
    """

    broker_type: ClassVar[str]

    if TYPE_CHECKING:
        # The Port member that the DLQ wrappers below call. Each adapter
        # defines it through ``BrokerPort``.
        @property
        def capabilities(self) -> BrokerCapabilities: ...

    def __init__(self, name: str, domain: "Domain", config: Mapping[str, Any]) -> None:
        self.name = name
        self.domain = domain
        # A copy: the broker never writes to the configuration it was given.
        self.config: Mapping[str, Any] = dict(config)

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
