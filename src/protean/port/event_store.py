from abc import ABCMeta, abstractmethod
from collections import deque
from typing import Any, Dict, List, Optional, Type, Union

from protean.core.aggregate import BaseAggregate
from protean.core.command import BaseCommand
from protean.core.event import BaseEvent
from protean.fields import Identifier
from protean.utils.eventing import Message


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
        stream: str,
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
        stream_nae: str,
        sql: str | None = None,
        position: int = 0,
        no_of_messages: int = 1000,
    ) -> List[Dict[str, Any]]:
        """Read messages from the event store.

        Implemented by the concrete event store adapter.
        """

    @abstractmethod
    def _read_last_message(self, stream) -> Dict[str, Any]:
        """Read the last message from the event store.

        Implemented by the concrete event store adapter.
        """

    def category(self, stream: str) -> str:
        if not stream:
            return ""

        stream_category, _, _ = stream.partition("-")
        return stream_category

    def read(
        self,
        stream: str,
        sql: str | None = None,
        position: int = 0,
        no_of_messages: int = 1000,
    ):
        raw_messages = self._read(
            stream, sql=sql, position=position, no_of_messages=no_of_messages
        )

        messages = []
        for raw_message in raw_messages:
            messages.append(Message.deserialize(raw_message))

        return messages

    def read_last_message(self, stream) -> Message:
        # FIXME Rename to read_last_stream_message
        raw_message = self._read_last_message(stream)
        if raw_message:
            return Message.deserialize(raw_message)

        return None

    def append(self, object: Union[BaseEvent, BaseCommand]) -> int:
        message = Message.from_domain_object(object)

        position = self._write(
            message.metadata.headers.stream,
            message.metadata.headers.type,
            message.data,
            metadata=message.metadata.to_dict(),
            expected_version=message.metadata.domain.expected_version
            if message.metadata.domain
            else None,
        )

        return position

    def load_aggregate(
        self, part_of: Type[BaseAggregate], identifier: Identifier
    ) -> Optional[BaseAggregate]:
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
            f"{part_of.meta_.stream_category}:snapshot-{identifier}"
        )

        if snapshot_message:
            # We have a snapshot, so initialize aggregate from snapshot
            #   and apply subsequent events
            aggregate = part_of(**snapshot_message["data"])
            position_in_snapshot = aggregate._version

            event_stream = deque(
                self._read(
                    f"{part_of.meta_.stream_category}-{identifier}",
                    position=aggregate._version + 1,
                )
            )

            events = []
            for event_message in event_stream:
                event = Message.deserialize(event_message).to_domain_object()
                aggregate._apply(event)
        else:
            # No snapshot, so initialize aggregate from events
            event_stream = deque(
                self._read(f"{part_of.meta_.stream_category}-{identifier}")
            )

            if not event_stream:
                return None

            events = []
            for event_message in event_stream:
                events.append(Message.deserialize(event_message).to_domain_object())

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
                >= self.domain.config["snapshot_threshold"]
            )
        ) or (
            not snapshot_message
            and len(event_stream) >= self.domain.config["snapshot_threshold"]
        ):
            # Snapshot is of type "SNAPSHOT" and contains only the aggregate's data
            #   (no metadata, so no event type)
            # This makes reconstruction of the aggregate from the snapshot easier,
            #   and also avoids spurious data just to satisfy Metadata's structure
            #   and conditions.
            self._write(
                f"{part_of.meta_.stream_category}:snapshot-{identifier}",
                "SNAPSHOT",
                aggregate.to_dict(),
            )

        return aggregate

    @abstractmethod
    def _data_reset(self) -> None:
        """Flush all events.

        Useful for running tests with a clean slate.
        """

    def _last_event_of_type(
        self, event_cls: Type[BaseEvent], stream_category: str = None
    ) -> BaseEvent:
        stream_category = stream_category or "$all"
        events = [
            event
            for event in self._read(stream_category)
            if event["type"] == event_cls.__type__
        ]

        return (
            Message.deserialize(events[-1]).to_domain_object()
            if len(events) > 0
            else None
        )

    def _events_of_type(
        self, event_cls: Type[BaseEvent], stream_category: str = None
    ) -> List[BaseEvent]:
        """Read events of a specific type in a given stream.

        This is a utility method, especially useful for testing purposes, that retrieves events of a
        specific type from the event store.

        If no stream is specified, events of the requested type will be retrieved from all streams.

        :param event_cls: Class of the event type to be retrieved. Subclass of `BaseEvent`.
        :param stream_category: Stream from which events are to be retrieved. String, optional, default is `None`
        :return: A list of events of `event_cls` type
        """
        stream_category = stream_category or "$all"
        return [
            Message.deserialize(event).to_domain_object()
            for event in self._read(stream_category)
            if event["type"] == event_cls.__type__
        ]
