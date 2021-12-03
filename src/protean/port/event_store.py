import json

from abc import ABCMeta, abstractmethod
from collections import deque
from typing import Any, Dict, List, Type

from protean import BaseEvent, BaseEventSourcedAggregate
from protean.fields import Identifier
from protean.reflection import id_field
from protean.utils import fully_qualified_name


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

    def append(self, aggregate: BaseEventSourcedAggregate, event: BaseEvent) -> int:
        identifier = getattr(aggregate, id_field(aggregate).field_name)

        return self._write(
            f"{aggregate.meta_.stream_name}-{identifier}",
            fully_qualified_name(event.__class__),
            event.to_dict(),  # FIXME Handle expected version
        )

    def load(
        self, aggregate_cls: Type[BaseEventSourcedAggregate], identifier: Identifier
    ) -> BaseEventSourcedAggregate:
        events = deque(self._read(f"{aggregate_cls.meta_.stream_name}-{identifier}"))

        first_event = events.popleft()
        aggregate = aggregate_cls(**json.loads(first_event["data"]))
        for event in events:
            aggregate._apply(event)

        return aggregate

    @abstractmethod
    def _data_reset(self) -> None:
        """Flush all events.

        Useful for running tests with a clean slate.
        """
