from datetime import datetime
from typing import Any, Dict, List

from protean import BaseAggregate, BaseRepository
from protean.globals import current_domain
from protean.port import BaseEventStore
from protean.utils import DomainObjects
from protean.utils.mixins import CoreMessage, MessageMetadata


class MemoryMessage(BaseAggregate, CoreMessage):
    class Meta:
        provider = "memory"


class MemoryMessageRepository(BaseRepository):
    class Meta:
        aggregate_cls = MemoryMessage

    def is_category(self, stream_name: str) -> bool:
        if not stream_name:
            return False

        return "-" not in stream_name

    def stream_version(self, stream_name: str):
        repo = current_domain.repository_for(MemoryMessage)
        results = (
            repo._dao.query.filter(stream_name=stream_name).order_by("-position").all()
        )

        return results.first.position if results.items else -1

    def write(
        self,
        stream_name: str,
        message_type: str,
        data: Dict,
        metadata: Dict = None,
        expected_version: int = None,
    ) -> int:
        pass

        # Fetch stream version
        _stream_version = self.stream_version(stream_name)

        if expected_version is not None and expected_version != _stream_version:
            raise ValueError(
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
                metadata=MessageMetadata(**metadata) if metadata else None,
                time=datetime.utcnow(),
            )
        )

        return next_position

    def read(
        self,
        stream_name: str,
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

        if stream_name == "$all":
            pass  # Don't filter on stream name
        elif self.is_category(stream_name):
            q = q.filter(stream_name__contains=stream_name)
        else:
            q = q.filter(stream_name=stream_name)

        items = q.all().items
        return [item.to_dict() for item in items]


class MemoryEventStore(BaseEventStore):
    def __init__(self, domain, conn_info) -> None:
        super().__init__("Memory", domain, conn_info)

        self.domain = domain
        self.domain._register_element(DomainObjects.AGGREGATE, MemoryMessage)
        self.domain.register(MemoryMessageRepository)

    def _write(
        self,
        stream_name: str,
        message_type: str,
        data: Dict,
        metadata: Dict = None,
        expected_version: int = None,
    ) -> int:
        repo = self.domain.repository_for(MemoryMessage)
        return repo.write(stream_name, message_type, data, metadata, expected_version)

    def _read(
        self,
        stream_name: str,
        sql: str = None,
        position: int = 0,
        no_of_messages: int = 1000,
    ) -> List[Dict[str, Any]]:
        repo = self.domain.repository_for(MemoryMessage)
        return repo.read(stream_name, sql, position, no_of_messages)

    def _read_last_message(self, stream_name) -> Dict[str, Any]:
        repo = self.domain.repository_for(MemoryMessage)

        messages = repo.read(stream_name)
        return messages[-1] if messages else None

    def _data_reset(self) -> None:
        """Flush all events.

        Useful for running tests with a clean slate.
        """
        repo = self.domain.repository_for(MemoryMessage)
        repo._dao._delete_all()
