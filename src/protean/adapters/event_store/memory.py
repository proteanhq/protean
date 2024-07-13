from datetime import UTC, datetime
from typing import Any, Dict, List

from protean.core.aggregate import BaseAggregate
from protean.core.repository import BaseRepository
from protean.globals import current_domain
from protean.port.event_store import BaseEventStore
from protean.utils.mixins import MessageRecord


class MemoryMessage(BaseAggregate, MessageRecord):
    pass


class MemoryMessageRepository(BaseRepository):
    def is_category(self, stream: str) -> bool:
        if not stream:
            return False

        return "-" not in stream

    def stream_version(self, stream: str):
        repo = current_domain.repository_for(MemoryMessage)
        results = repo._dao.query.filter(stream=stream).order_by("-position").all()

        return results.first.position if results.items else -1

    def write(
        self,
        stream: str,
        message_type: str,
        data: Dict,
        metadata: Dict = None,
        expected_version: int = None,
    ) -> int:
        # Fetch stream version
        _stream_version = self.stream_version(stream)

        if expected_version is not None and expected_version != _stream_version:
            raise ValueError(
                f"Wrong expected version: {expected_version} "
                f"(Stream: {stream}, Stream Version: {_stream_version})"
            )

        next_position = _stream_version + 1

        self.add(
            MemoryMessage(
                stream=stream,
                position=next_position,
                type=message_type,
                data=data,
                metadata=metadata,
                time=datetime.now(UTC),
            )
        )

        return next_position

    def read(
        self,
        stream: str,
        sql: str = None,
        position: int = 0,
        no_of_messages: int = 1000,
    ):
        repo = current_domain.repository_for(MemoryMessage)
        q = (
            repo._dao.query.filter(position__gte=position)
            .order_by("position")
            .limit(no_of_messages)
        )

        if stream == "$all":
            pass  # Don't filter on stream name or category
        elif self.is_category(stream):
            # If filtering on category, ensure the supplied stream name
            #   is the only thing in the category.
            # Eg. If stream is 'user', then only 'user' should be in the category,
            #   and not even `user:command`
            q = q.filter(stream__contains=f"{stream}-")
        else:
            q = q.filter(stream=stream)

        items = q.all().items
        return [item.to_dict() for item in items]


class MemoryEventStore(BaseEventStore):
    def __init__(self, domain, conn_info) -> None:
        super().__init__("Memory", domain, conn_info)

        self.domain = domain
        self.domain.register(MemoryMessage, provider="memory")
        self.domain.register(MemoryMessageRepository, part_of=MemoryMessage)

    def _write(
        self,
        stream: str,
        message_type: str,
        data: Dict,
        metadata: Dict = None,
        expected_version: int = None,
    ) -> int:
        repo = self.domain.repository_for(MemoryMessage)
        return repo.write(stream, message_type, data, metadata, expected_version)

    def _read(
        self,
        stream: str,
        sql: str = None,
        position: int = 0,
        no_of_messages: int = 1000,
    ) -> List[Dict[str, Any]]:
        repo = self.domain.repository_for(MemoryMessage)
        return repo.read(stream, sql, position, no_of_messages)

    def _read_last_message(self, stream) -> Dict[str, Any]:
        repo = self.domain.repository_for(MemoryMessage)

        messages = repo.read(stream)
        return messages[-1] if messages else None

    def _data_reset(self) -> None:
        """Flush all events.

        Useful for running tests with a clean slate.
        """
        repo = self.domain.repository_for(MemoryMessage)
        repo._dao._delete_all()
