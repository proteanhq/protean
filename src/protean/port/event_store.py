from abc import ABCMeta, abstractmethod
from collections import deque
from typing import Any, Dict, List, Optional, Type

from protean import BaseCommand, BaseEvent, BaseEventSourcedAggregate
from protean.fields import Identifier
from protean.utils.mixins import Message


class BaseEventStore(metaclass=ABCMeta):
    """This class outlines the base event store capabilities
    to be implemented in all supported event store adapters.

    It is also a marker interface for registering event store
    classes with the domain.
    """

    # FIXME Move this to config file
    SNAPSHOT_THRESHOLD = 10

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

        position = self._write(
            message.stream_name,
            message.type,
            message.data,
            metadata=message.metadata.to_dict(),
            expected_version=message.expected_version,
        )

        # Increment aggregate's version as we process events
        #    to correctly handle expected version
        aggregate._version += 1

        return position

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
    ) -> Optional[BaseEventSourcedAggregate]:
        """Load an aggregate from underlying events.

        The first event is used to initialize the aggregate, after which each event is
        applied in sequence until the end.

        A snapshot, if one exists, is loaded first and subsequent events are
        applied on it. If there are more than SNAPSHOT_THRESHOLD events since snapshot,
        a new snapshot is written to the store.

        Args:
            aggregate_cls (Type[BaseEventSourcedAggregate]): The EventSourced Aggregate's class
            identifier (Identifier): Unique aggregate identifier

        Returns:
            Optional[BaseEventSourcedAggregate]: Return fully-formed aggregate when events exist,
                or None.
        """
        snapshot = self._read_last_message(
            f"{aggregate_cls.meta_.stream_name}:snapshot-{identifier}"
        )

        if snapshot:
            aggregate = aggregate_cls(**snapshot["data"])
            position_in_snapshot = snapshot["data"]["_version"]

            events = deque(
                self._read(
                    f"{aggregate_cls.meta_.stream_name}-{identifier}",
                    position=position_in_snapshot + 1,
                )
            )
        else:
            events = deque(
                self._read(f"{aggregate_cls.meta_.stream_name}-{identifier}")
            )

            if not events:
                return None

            # Handle first event separately to initialize the aggregate
            first_event = events.popleft()
            aggregate = aggregate_cls(**first_event["data"])

            # Also apply the first event in case a method has been specified
            aggregate._apply(first_event)
            aggregate._version += 1

        # Apply all other events one-by-one
        for event in events:
            aggregate._apply(event)
            aggregate._version += 1

        # If there are more events than SNAPSHOT_THRESHOLD, create a new snapshot
        if (
            snapshot
            and len(events) > 1
            and (
                events[-1]["position"] - position_in_snapshot >= self.SNAPSHOT_THRESHOLD
            )
        ) or (
            not snapshot and len(events) + 1 >= self.SNAPSHOT_THRESHOLD
        ):  # Account for the first event that was popped
            self._write(
                f"{aggregate_cls.meta_.stream_name}:snapshot-{identifier}",
                "SNAPSHOT",
                aggregate.to_dict(),
            )

        return aggregate

    @abstractmethod
    def _data_reset(self) -> None:
        """Flush all events.

        Useful for running tests with a clean slate.
        """
