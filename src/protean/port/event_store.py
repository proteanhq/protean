import json

from abc import ABCMeta, abstractmethod
from collections import deque
from typing import Any, Dict, List, Type

from protean import BaseCommand, BaseEvent, BaseEventSourcedAggregate
from protean.fields import Identifier
from protean.utils.mixins import Message


class BaseEventStore(metaclass=ABCMeta):
    """This class outlines the base event store capabilities
    to be implemented in all supported event store adapters.

    It is also a marker interface for registering event store
    classes with the domain.
    """

    def __init__(
        self, name: str, domain: Any, conn_info: Dict[str, str]
    ) -> None:  # FIXME Any should be Domain
        self.name = name
        self.domain = domain
        self.conn_info = conn_info

    @abstractmethod
    def _write(
        self,
        stream_name: str,
        message_type: str,
        data: Dict,
        metadata: Dict = None,
        expected_version: int = None,
    ) -> int:
        pass

    @abstractmethod
    def _read(
        self,
        stream_name: str,
        sql: str = None,
        position: int = 0,
        no_of_messages: int = 1000,
    ) -> List[Dict[str, Any]]:
        pass

    @abstractmethod
    def _read_last_message(self, stream_name) -> Dict[str, Any]:
        pass

    def category(self, stream_name: str) -> str:
        if not stream_name:
            return ""

        stream_category, _, _ = stream_name.partition("-")
        return stream_category

    def read(
        self,
        stream_name: str,
        sql: str = None,
        position: int = 0,
        no_of_messages: int = 1000,
    ):
        raw_messages = self._read(
            stream_name, sql=sql, position=position, no_of_messages=no_of_messages
        )

        messages = []
        for raw_message in raw_messages:
            messages.append(Message.from_dict(raw_message))

        return messages

    def append_aggregate_event(
        self, aggregate: BaseEventSourcedAggregate, event: BaseEvent
    ) -> int:
        message = Message.to_aggregate_event_message(aggregate, event)

        return self._write(
            message.stream_name,
            message.type,
            message.data,
            metadata=message.metadata.to_dict(),
        )

    def append_event(self, event: BaseEvent) -> int:
        message = Message.to_event_message(event)

        return self._write(
            message.stream_name,
            message.type,
            message.data,
            metadata=message.metadata.to_dict(),
        )

    def append_command(self, command: BaseCommand) -> int:
        message = Message.to_command_message(command)

        return self._write(
            message.stream_name,
            message.type,
            message.data,
            metadata=message.metadata.to_dict(),
        )

    def load_aggregate(
        self, aggregate_cls: Type[BaseEventSourcedAggregate], identifier: Identifier
    ) -> BaseEventSourcedAggregate:
        events = deque(self._read(f"{aggregate_cls.meta_.stream_name}-{identifier}"))

        if not events:
            return None

        # Handle first event separately, since we need to initialize the aggregate with its data
        first_event = events.popleft()
        aggregate = aggregate_cls(**json.loads(first_event["data"]))
        aggregate._apply(first_event)

        for event in events:
            aggregate._apply(event)

        return aggregate

    @abstractmethod
    def _data_reset(self) -> None:
        """Flush all events.

        Useful for running tests with a clean slate.
        """
