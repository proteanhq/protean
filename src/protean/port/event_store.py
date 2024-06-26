from abc import ABCMeta, abstractmethod
from collections import deque
from typing import Any, Dict, List, Optional, Type, Union

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
        metadata: Dict | None = None,
        expected_version: int | None = None,
    ) -> int:
        """Write a message to the event store.

        Returns the position of the message in the stream.

        Implemented by the concrete event store adapter.
        """

    @abstractmethod
    def _read(
        self,
        stream_name: str,
        sql: str | None = None,
        position: int = 0,
        no_of_messages: int = 1000,
    ) -> List[Dict[str, Any]]:
        """Read messages from the event store.

        Implemented by the concrete event store adapter.
        """

    @abstractmethod
    def _read_last_message(self, stream_name) -> Dict[str, Any]:
        """Read the last message from the event store.

        Implemented by the concrete event store adapter.
        """

    def category(self, stream_name: str) -> str:
        if not stream_name:
            return ""

        stream_category, _, _ = stream_name.partition("-")
        return stream_category

    def read(
        self,
        stream_name: str,
        sql: str | None = None,
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

    def read_last_message(self, stream_name) -> Message:
        # FIXME Rename to read_last_stream_message
        raw_message = self._read_last_message(stream_name)
        return Message.from_dict(raw_message)

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

    def append(self, object: Union[BaseEvent, BaseCommand]) -> int:
        message = Message.to_message(object)

        return self._write(
            message.stream_name,
            message.type,
            message.data,
            metadata=message.metadata.to_dict(),
        )

    def load_aggregate(
        self, part_of: Type[BaseEventSourcedAggregate], identifier: Identifier
    ) -> Optional[BaseEventSourcedAggregate]:
        """Load an aggregate from underlying events.

        The first event is used to initialize the aggregate, after which each event is
        applied in sequence until the end.

        A snapshot, if one exists, is loaded first and subsequent events are
        applied on it. If there are more than SNAPSHOT_THRESHOLD events since snapshot,
        a new snapshot is written to the store.

        Args:
            part_of (Type[BaseEventSourcedAggregate]): The EventSourced Aggregate's class
            identifier (Identifier): Unique aggregate identifier

        Returns:
            Optional[BaseEventSourcedAggregate]: Return fully-formed aggregate when events exist,
                or None.
        """
        snapshot_message = self._read_last_message(
            f"{part_of.meta_.stream_name}:snapshot-{identifier}"
        )

        if snapshot_message:
            # We have a snapshot, so initialize aggregate from snapshot
            #   and apply subsequent events
            aggregate = part_of(**snapshot_message["data"])
            position_in_snapshot = aggregate._version

            event_stream = deque(
                self._read(
                    f"{part_of.meta_.stream_name}-{identifier}",
                    position=aggregate._version + 1,
                )
            )

            events = []
            for event_message in event_stream:
                event = Message.from_dict(event_message).to_object()
                aggregate._apply(event)
        else:
            # No snapshot, so initialize aggregate from events
            event_stream = deque(
                self._read(f"{part_of.meta_.stream_name}-{identifier}")
            )

            if not event_stream:
                return None

            events = []
            for event_message in event_stream:
                events.append(Message.from_dict(event_message).to_object())

            aggregate = part_of.from_events(events)

        ####################################
        # ADD SNAPSHOT IF BEYOND THRESHOLD #
        ####################################
        # FIXME Delay creating snapshot or push to a background process
        # If there are more events than SNAPSHOT_THRESHOLD, create a new snapshot
        if (
            snapshot_message
            and len(event_stream) > 1
            and (
                event_stream[-1]["position"] - position_in_snapshot
                >= self.domain.config["SNAPSHOT_THRESHOLD"]
            )
        ) or (
            not snapshot_message
            and len(event_stream) >= self.domain.config["SNAPSHOT_THRESHOLD"]
        ):
            # Snapshot is of type "SNAPSHOT" and contains only the aggregate's data
            #   (no metadata, so no event type)
            # This makes reconstruction of the aggregate from the snapshot easier,
            #   and also avoids spurious data just to satisfy Metadata's structure
            #   and conditions.
            self._write(
                f"{part_of.meta_.stream_name}:snapshot-{identifier}",
                "SNAPSHOT",
                aggregate.to_dict(),
            )

        return aggregate

    @abstractmethod
    def _data_reset(self) -> None:
        """Flush all events.

        Useful for running tests with a clean slate.
        """
