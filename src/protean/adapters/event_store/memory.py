import copy
import threading
from collections.abc import Iterable, Iterator, Mapping
from itertools import islice
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from protean.exceptions import ExpectedVersionError, NotSupportedError
from protean.infra.registry import event_stores
from protean.port.event_store import (
    EventStoreCapabilities,
    EventStoreHealth,
    EventStorePort,
    RawMessage,
)
from protean.utils.eventing import Metadata
from protean.utils.globals import _domain_now

if TYPE_CHECKING:
    from protean.domain import Domain


def _in_category(stream_name: str, category: str) -> bool:
    """Return whether ``stream_name`` belongs to ``category``.

    A category has no ``-``, so a stream named ``<category>`` or starting with
    ``<category>-`` is in exactly that category. The match leaves out a longer
    category that shares the text (``poweruser`` or ``users`` for ``user``) and
    the snapshot streams (``<category>:snapshot-<id>``).
    """
    # Message DB's ``category(stream_name)`` is the text before the first
    # ``-``, so the stream ``user`` is in category ``user`` too.
    return stream_name == category or stream_name.startswith(f"{category}-")


def _copy(row: RawMessage) -> RawMessage:
    # A read returns copies, so a caller cannot change a stored row through
    # the result.
    result: RawMessage = copy.deepcopy(row)
    return result


def _copies(rows: Iterable[RawMessage]) -> list[RawMessage]:
    return [_copy(row) for row in rows]


class MemoryEventStore(EventStorePort):
    """An event store that keeps its messages in process memory.

    Messages live in an append-only list, and ``global_position`` is a row's
    list index plus one. A write is visible at once and does not take part in
    a Unit of Work, so a rollback leaves it in place, as on Message DB.
    """

    def __init__(self, name: str, domain: "Domain", config: Mapping[str, Any]) -> None:
        self.name = name
        self.domain = domain
        self.config = config

        self._messages: list[RawMessage] = []
        # Stream name to the list indexes of its rows, in position order.
        self._streams: dict[str, list[int]] = {}
        # Not reentrant: only public methods take it, and they never call one
        # another while holding it.
        self._lock = threading.Lock()

    @property
    def capabilities(self) -> EventStoreCapabilities:
        # The lock covers the version check and the append, and a write is
        # visible to the next version check at once, so EXPECTED_VERSION and
        # CATEGORY_COMMIT_ORDER hold for concurrent writers. Events live in
        # process memory and are lost on exit, so the store is not DURABLE.
        return EventStoreCapabilities.CONSISTENT

    def write_message(
        self,
        stream_name: str,
        message_type: str,
        data: Mapping[str, Any],
        metadata: Mapping[str, Any] | None = None,
        expected_version: int | None = None,
    ) -> int:
        with self._lock:
            index = self._streams.get(stream_name, [])
            stream_version = len(index) - 1

            if expected_version is not None and expected_version != stream_version:
                raise ExpectedVersionError(
                    f"Wrong expected version: {expected_version} "
                    f"(Stream: {stream_name}, Stream Version: {stream_version})"
                )

            position = stream_version + 1
            # Build the row before touching the store, so a row that fails to
            # build (rejected metadata, for one) leaves the stream unchanged.
            row = RawMessage(
                id=str(uuid4()),
                stream_name=stream_name,
                type=message_type,
                position=position,
                global_position=len(self._messages) + 1,
                data=copy.deepcopy(dict(data)),
                metadata=_normalized_metadata(metadata),
                time=_domain_now(),
            )
            self._streams.setdefault(stream_name, []).append(len(self._messages))
            self._messages.append(row)
            return position

    def get_stream_messages(
        self, stream_name: str, position: int = 0, limit: int = 1000
    ) -> list[RawMessage]:
        with self._lock:
            index = self._streams.get(stream_name, [])
            start = max(position, 0)
            return _copies(self._messages[i] for i in index[start : start + limit])

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
        with self._lock:
            rows = (
                row
                for row in self._from_global_position(position)
                if _in_category(row["stream_name"], category)
            )
            return _copies(islice(rows, limit))

    def get_all_messages(
        self, position: int = 0, limit: int = 1000
    ) -> list[RawMessage]:
        with self._lock:
            return _copies(islice(self._from_global_position(position), limit))

    # A tail read takes the newest row however long the stream is. The
    # append-only recovery-checkpoint stream grows past one read page over
    # many restarts.
    def get_last_stream_message(self, stream_name: str) -> RawMessage | None:
        with self._lock:
            index = self._streams.get(stream_name)
            return _copy(self._messages[index[-1]]) if index else None

    def get_last_category_message(self, category: str) -> RawMessage | None:
        with self._lock:
            for row in reversed(self._messages):
                if _in_category(row["stream_name"], category):
                    return _copy(row)
            return None

    def get_last_message(self) -> RawMessage | None:
        with self._lock:
            return _copy(self._messages[-1]) if self._messages else None

    def stream_ids(self, category: str) -> list[str]:
        with self._lock:
            names = [
                name
                for name, index in self._streams.items()
                if index and _in_category(name, category)
            ]
        identifiers: set[str] = set()
        for name in names:
            _, sep, ident = name.partition("-")
            if sep and ident:
                identifiers.add(ident)
        return sorted(identifiers)

    def ping(self) -> bool:
        return True

    def health(self) -> EventStoreHealth:
        return EventStoreHealth(reachable=True, pool=None)

    def get_connection(self) -> list[RawMessage]:
        """Return the live list of stored rows, in global-position order.

        A change to the list or to a row in it changes the store. Test seeding
        use only; the per-stream index does not see rows appended here.
        """
        return self._messages

    def clear(self) -> None:
        """Delete every message. Test-harness use only."""
        with self._lock:
            self._messages.clear()
            self._streams.clear()

    def _from_global_position(self, position: int) -> Iterator[RawMessage]:
        # Filter on the stored value rather than slice by index: a test can
        # seed a row with a gap in ``global_position`` through
        # ``get_connection()``.
        return (row for row in self._messages if row["global_position"] >= position)


def _normalized_metadata(
    metadata: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    # Round-trip through ``Metadata`` so a stored row carries every metadata
    # key, each with its default when the writer left it out.
    if metadata is None:
        return None
    result: dict[str, Any] = Metadata.model_validate(dict(metadata)).to_dict()
    return result


def register() -> None:
    """Register MemoryEventStore with Protean as the `memory` event store."""
    event_stores.register(
        "memory", "protean.adapters.event_store.memory.MemoryEventStore"
    )


_PORT_CHECK: type[EventStorePort] = MemoryEventStore
