from __future__ import annotations

from abc import abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import Flag, auto
from typing import TYPE_CHECKING, Any, Protocol, TypedDict

if TYPE_CHECKING:
    from protean.domain import Domain
    from protean.port.health import PoolStats

# Snapshot rows are written with ``message_type="SNAPSHOT"`` and no metadata
# (see ``EventStore._load_aggregate_current`` and ``EventStore.create_snapshot``
# in ``protean.infra.event_store``). They hold an
# aggregate's serialized state, not an event or command, so the read layer
# skips them: ``Message.deserialize`` would raise on their ``None`` metadata,
# and callers of ``read``/``read_all`` expect events and commands only.
SNAPSHOT_TYPE = "SNAPSHOT"


class EventStoreCapabilities(Flag):
    """The guarantees an event store makes.

    Each event store declares its flags on ``capabilities``. Check a guarantee
    with ``EventStoreCapabilities.DURABLE in store.capabilities``.
    """

    WRITE = auto()  # Append a message and return its stream position
    READ_STREAM = auto()  # Read one stream by stream position
    READ_CATEGORY = auto()  # Read a category by global position, inclusive
    READ_ALL = auto()  # Read the whole store by global position, inclusive
    EXPECTED_VERSION = auto()  # A stale expected version raises and writes nothing
    CATEGORY_COMMIT_ORDER = auto()  # Category writes become visible in position order
    CONSUMER_GROUPS = auto()  # A category read can be split across group members
    DURABLE = auto()  # Messages survive a process restart
    SCHEMA_MANAGEMENT = auto()  # The store creates and drops its own tables

    # Convenience Capability Sets
    BASIC = WRITE | READ_STREAM | READ_CATEGORY | READ_ALL

    CONSISTENT = BASIC | EXPECTED_VERSION | CATEGORY_COMMIT_ORDER

    PRODUCTION = CONSISTENT | DURABLE


class RawMessage(TypedDict):
    """One row as an event store returns it.

    ``position`` is the row's place in its stream, from 0 with no gaps.
    ``global_position`` is its place in the whole store and may have gaps. A
    snapshot row has ``type == "SNAPSHOT"`` and ``metadata`` of ``None``.
    """

    id: str
    stream_name: str
    type: str
    position: int
    global_position: int
    data: dict[str, Any] | None
    metadata: dict[str, Any] | None
    time: datetime


def row_data(row: RawMessage) -> dict[str, Any]:
    """Return the row's ``data``, or an empty dict when the row has none."""
    return row["data"] or {}


@dataclass(frozen=True)
class EventStoreHealth:
    """The health of an event store.

    ``reachable`` is the result of ``ping()``. ``pool`` describes the
    adapter's connection pool, or is ``None`` for an adapter without one or
    whose pool does not exist yet.
    """

    reachable: bool
    pool: PoolStats | None


class EventStorePort(Protocol):
    """The operations an event-store adapter implements.

    Every read includes the row at ``position``. A stream read pages by the
    stream ``position``. A category read and an all read page by
    ``global_position`` (ADR-0024). A category read returns only streams whose
    category equals ``category`` exactly, and never a snapshot stream
    (``<category>:snapshot-<id>``).
    """

    name: str

    def __init__(self, name: str, domain: Domain, config: Mapping[str, Any]) -> None:
        """Build the adapter named ``name`` for ``domain`` from ``config``."""

    @property
    @abstractmethod
    def capabilities(self) -> EventStoreCapabilities:
        """The guarantees this event store makes."""

    @abstractmethod
    def write_message(
        self,
        stream_name: str,
        message_type: str,
        data: Mapping[str, Any],
        metadata: Mapping[str, Any] | None = None,
        expected_version: int | None = None,
    ) -> int | None:
        """Append a message to ``stream_name`` and return its stream position.

        Returns ``None`` when the store holds the message to write when the
        active Unit of Work commits, and the position is assigned then. The
        memory and Message DB stores always return the position.

        Raises:
            ExpectedVersionError: When ``expected_version`` is given and is not
                the stream's current version. Nothing is written. A store that
                holds the message raises it from the Unit of Work's commit.
        """

    @abstractmethod
    def get_stream_messages(
        self, stream_name: str, position: int = 0, limit: int = 1000
    ) -> list[RawMessage]:
        """Return up to ``limit`` rows of one stream from stream ``position``."""

    @abstractmethod
    def get_category_messages(
        self,
        category: str,
        position: int = 0,
        limit: int = 1000,
        *,
        consumer_group_member: int | None = None,
        consumer_group_size: int | None = None,
    ) -> list[RawMessage]:
        """Return up to ``limit`` rows of ``category`` from ``global_position``.

        With ``consumer_group_member`` and ``consumer_group_size``, return only
        the streams that belong to that member of the group.

        Raises:
            NotSupportedError: When a consumer-group argument is given and the
                adapter does not declare ``CONSUMER_GROUPS``.
            ValueError: When an adapter that declares ``CONSUMER_GROUPS``
                gets only one of the two consumer-group arguments.
        """

    @abstractmethod
    def get_all_messages(
        self, position: int = 0, limit: int = 1000
    ) -> list[RawMessage]:
        """Return up to ``limit`` rows of the whole store from ``global_position``."""

    @abstractmethod
    def get_last_stream_message(self, stream_name: str) -> RawMessage | None:
        """Return the newest row of one stream, or ``None`` when it is empty."""

    @abstractmethod
    def get_last_category_message(self, category: str) -> RawMessage | None:
        """Return the row of ``category`` with the highest ``global_position``.

        Returns ``None`` when the category is empty.
        """

    @abstractmethod
    def get_last_message(self) -> RawMessage | None:
        """Return the row with the highest ``global_position`` in the store.

        Returns ``None`` when the store is empty.
        """

    @abstractmethod
    def stream_ids(self, category: str) -> list[str]:
        """Return the sorted, unique identifiers of the streams in ``category``.

        A stream ``<category>-<id>`` gives ``<id>``. Snapshot streams are left
        out.
        """

    @abstractmethod
    def ping(self) -> bool:
        """Return whether the store answers. Never raises."""

    @abstractmethod
    def health(self) -> EventStoreHealth:
        """Return the store's health record."""

    @abstractmethod
    def get_connection(self) -> object:
        """Return the native client, or ``None`` for an adapter without one."""

    @abstractmethod
    def clear(self) -> None:
        """Delete every message. Test-harness use only."""

    def close(self) -> None:
        """Release the store's connections. The default does nothing."""
        return

    def create_schema(self) -> None:
        """Create the store's tables, behind ``SCHEMA_MANAGEMENT``.

        The default does nothing.
        """
        return

    def drop_schema(self) -> None:
        """Drop the store's tables, behind ``SCHEMA_MANAGEMENT``.

        The default does nothing.
        """
        return
