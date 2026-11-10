import threading
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, cast
from uuid import uuid4

from pydantic import Field

from protean.core.aggregate import BaseAggregate
from protean.core.repository import BaseRepository
from protean.exceptions import ExpectedVersionError, NotSupportedError
from protean.infra.registry import event_stores
from protean.port.event_store import (
    BaseEventStore,
    EventStoreCapabilities,
    EventStoreHealth,
    EventStorePort,
    RawMessage,
)
from protean.utils import OptionalStdlibDatetime
from protean.utils.eventing import Metadata
from protean.utils.globals import _domain_now, current_domain

if TYPE_CHECKING:
    from protean.domain import Domain


class MemoryMessage(BaseAggregate):
    # Primary key. The ordinal position of the message in the entire message store.
    # Global position may have gaps.
    global_position: int | None = Field(
        default=None,
        json_schema_extra={"identifier": True, "increment": True},
    )

    # The ordinal position of the message in its stream.
    # Position is gapless.
    position: int | None = None

    # Message creation time
    time: OptionalStdlibDatetime = None

    # Unique ID of the message
    id: str = Field(default_factory=lambda: str(uuid4()))

    # Name of stream to which the message is written
    stream_name: str | None = None

    # The type of the message
    type: str | None = None

    # JSON representation of the message body
    data: dict[str, Any] | None = None

    # JSON representation of the message metadata
    metadata: Metadata | None = None


class MemoryMessageRepository(BaseRepository):
    # Class-level lock: repositories are instantiated per repository_for()
    # call, so an instance-level lock would not be shared across callers.
    _write_lock = threading.Lock()

    def stream_version(self, stream_name: str) -> int:
        repo = current_domain.repository_for(MemoryMessage)
        results = (
            repo._dao.query.filter(stream_name=stream_name)
            .order_by("-position")
            .limit(1)
            .all()
        )

        if results.items:
            assert results.first is not None
            position: int = results.first.position
            return position
        return -1

    def write(
        self,
        stream_name: str,
        message_type: str,
        data: dict[str, Any],
        metadata: dict[str, Any] | None = None,
        expected_version: int | None = None,
    ) -> int:
        with self._write_lock:
            # Version check + write are now atomic under the lock
            _stream_version = self.stream_version(stream_name)

            if expected_version is not None and expected_version != _stream_version:
                raise ExpectedVersionError(
                    f"Wrong expected version: {expected_version} "
                    f"(Stream: {stream_name}, Stream Version: {_stream_version})"
                )

            next_position = _stream_version + 1

            self.add(
                MemoryMessage(
                    stream_name=stream_name,
                    position=next_position,
                    type=message_type,
                    data=data,
                    # ``metadata`` arrives as a plain dict (see
                    # ``BaseEventStore.append`` -> ``metadata.to_dict()``); build
                    # the ``Metadata`` value object explicitly via the typed
                    # pydantic API. This is identical to pydantic's implicit
                    # dict->model coercion but visible to static checkers.
                    metadata=Metadata.model_validate(metadata)
                    if metadata is not None
                    else None,
                    time=_domain_now(),
                )
            )

            return next_position

    def _query(self) -> Any:
        repo = current_domain.repository_for(MemoryMessage)
        return repo._dao.query

    def read_stream(
        self, stream_name: str, position: int, limit: int
    ) -> list[RawMessage]:
        """Read one stream by its own per-stream ``position``."""
        q = (
            self._query()
            .filter(stream_name=stream_name, position__gte=position)
            .order_by("position")
        )
        return _rows(q.limit(limit))

    def read_category(
        self, category: str, position: int, limit: int
    ) -> list[RawMessage]:
        """Read a category by ``global_position`` (ADR-0024).

        A category has no ``-``, so the ``<category>-`` prefix matches exactly
        that category's streams. It leaves out a longer category that ends with
        the same text (``poweruser`` for ``user``) and the snapshot streams
        (``<category>:snapshot-<id>``).
        """
        q = (
            self._query()
            .filter(
                stream_name__startswith=f"{category}-", global_position__gte=position
            )
            .order_by("global_position")
        )
        return _rows(q.limit(limit))

    def read_all(self, position: int, limit: int) -> list[RawMessage]:
        """Read the whole store by ``global_position`` (ADR-0024)."""
        q = (
            self._query()
            .filter(global_position__gte=position)
            .order_by("global_position")
        )
        return _rows(q.limit(limit))

    # A tail read orders descending and takes one row, so it returns the newest
    # row however long the stream is. The append-only recovery-checkpoint stream
    # grows past one read page over many restarts.
    def last_in_stream(self, stream_name: str) -> RawMessage | None:
        q = self._query().filter(stream_name=stream_name).order_by("-position")
        return _first(q.limit(1))

    def last_in_category(self, category: str) -> RawMessage | None:
        q = (
            self._query()
            .filter(stream_name__startswith=f"{category}-")
            .order_by("-global_position")
        )
        return _first(q.limit(1))

    def last_in_store(self) -> RawMessage | None:
        return _first(self._query().order_by("-global_position").limit(1))


def _rows(query: Any) -> list[RawMessage]:
    return [cast(RawMessage, item.to_dict()) for item in query.all().items]


def _first(query: Any) -> RawMessage | None:
    rows = _rows(query)
    return rows[0] if rows else None


class MemoryEventStore(BaseEventStore):
    def __init__(self, name: str, domain: "Domain", config: Mapping[str, Any]) -> None:
        super().__init__(name, domain, config)

        self.domain.register(MemoryMessage, internal=True, provider="memory")
        self.domain.register(
            MemoryMessageRepository, internal=True, part_of=MemoryMessage
        )
        # Explicitly register with providers so the internal repository is
        # discoverable (registry.repositories filters out internal elements).
        self.domain.providers._register_repository(
            MemoryMessage, MemoryMessageRepository
        )

    @property
    def capabilities(self) -> EventStoreCapabilities:
        # EXPECTED_VERSION and CATEGORY_COMMIT_ORDER hold while one Unit of
        # Work writes at a time. The write lock covers the version check and
        # the append to the session. The version check cannot see rows that
        # another Unit of Work has not committed yet, so two overlapping Units
        # of Work can both pass it and commit out of global-position order. Events live in process memory
        # and are lost on exit, so the store is not DURABLE.
        return EventStoreCapabilities.CONSISTENT

    def _repo(self) -> MemoryMessageRepository:
        return cast(MemoryMessageRepository, self.domain.repository_for(MemoryMessage))

    def write_message(
        self,
        stream_name: str,
        message_type: str,
        data: Mapping[str, Any],
        metadata: Mapping[str, Any] | None = None,
        expected_version: int | None = None,
    ) -> int:
        return self._repo().write(
            stream_name,
            message_type,
            dict(data),
            dict(metadata) if metadata is not None else None,
            expected_version,
        )

    def get_stream_messages(
        self, stream_name: str, position: int = 0, limit: int = 1000
    ) -> list[RawMessage]:
        return self._repo().read_stream(stream_name, position, limit)

    def get_category_messages(
        self,
        category: str,
        position: int = 0,
        limit: int = 1000,
        *,
        consumer_group_member: int | None = None,
        consumer_group_size: int | None = None,
    ) -> list[RawMessage]:
        if consumer_group_member is not None or consumer_group_size is not None:
            raise NotSupportedError(
                "The memory event store does not support consumer groups"
            )
        return self._repo().read_category(category, position, limit)

    def get_all_messages(
        self, position: int = 0, limit: int = 1000
    ) -> list[RawMessage]:
        return self._repo().read_all(position, limit)

    def get_last_stream_message(self, stream_name: str) -> RawMessage | None:
        return self._repo().last_in_stream(stream_name)

    def get_last_category_message(self, category: str) -> RawMessage | None:
        return self._repo().last_in_category(category)

    def get_last_message(self) -> RawMessage | None:
        return self._repo().last_in_store()

    def stream_ids(self, category: str) -> list[str]:
        rows = self._repo().read_category(category, 0, 1_000_000)
        identifiers: set[str] = set()
        for row in rows:
            _, sep, ident = row["stream_name"].partition("-")
            if sep and ident:
                identifiers.add(ident)
        return sorted(identifiers)

    def ping(self) -> bool:
        return True

    def health(self) -> EventStoreHealth:
        return EventStoreHealth(reachable=True, pool=None)

    def get_connection(self) -> None:
        return None

    def clear(self) -> None:
        """Delete every message. Test-harness use only."""
        repo = self.domain.repository_for(MemoryMessage)
        repo._dao._delete_all()


def register() -> None:
    """Register MemoryEventStore with Protean as the `memory` event store."""
    event_stores.register(
        "memory", "protean.adapters.event_store.memory.MemoryEventStore"
    )


_PORT_CHECK: type[EventStorePort] = MemoryEventStore
