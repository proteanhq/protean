from abc import ABCMeta, abstractmethod
from collections import deque
from datetime import datetime
from typing import Any, Dict, List, Optional, Type, Union

from protean.core.aggregate import BaseAggregate
from protean.core.command import BaseCommand
from protean.core.event import BaseEvent
from protean.exceptions import IncorrectUsageError, ObjectNotFoundError
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

    def close(self) -> None:
        """Close the event store and release all connections.

        Subclasses that hold external resources (connection pools, sockets,
        etc.) should override this to perform cleanup.  The default
        implementation is a no-op so that adapters without external
        resources (e.g. the in-memory store) work without changes.
        """

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

    def read_last_message(self, stream) -> Optional[Message]:
        # FIXME Rename to read_last_stream_message
        raw_message = self._read_last_message(stream)
        if raw_message:
            return Message.deserialize(raw_message)

        return None

    def append(self, object: Union[BaseEvent, BaseCommand]) -> int:
        message = Message.from_domain_object(object)
        assert message.metadata is not None, "Message metadata cannot be None"

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
        self,
        part_of: Type[BaseAggregate],
        identifier: str,
        *,
        at_version: int | None = None,
        as_of: datetime | None = None,
    ) -> Optional[BaseAggregate]:
        """Load an aggregate from underlying events.

        By default, reconstitutes the aggregate to its current (latest) state.
        When ``at_version`` or ``as_of`` is provided, reconstitutes a historical
        snapshot of the aggregate — a *temporal query*.

        Args:
            part_of: The EventSourced Aggregate's class.
            identifier: Unique aggregate identifier.
            at_version: Reconstitute to this exact version (0-indexed).
                Version 0 is the state after the first event.
            as_of: Reconstitute the aggregate as of this timestamp.
                Only events written on or before ``as_of`` are applied.

        Returns:
            The fully-formed aggregate, or ``None`` when no events exist
            (and no temporal param was given that would raise instead).
        """
        if as_of is not None:
            return self._load_aggregate_as_of(part_of, identifier, as_of)
        if at_version is not None:
            return self._load_aggregate_at_version(part_of, identifier, at_version)
        return self._load_aggregate_current(part_of, identifier)

    # ------------------------------------------------------------------
    # Private helpers for load_aggregate
    # ------------------------------------------------------------------

    def _load_aggregate_current(
        self, part_of: Type[BaseAggregate], identifier: str
    ) -> Optional[BaseAggregate]:
        """Load the aggregate at its latest version (existing behaviour)."""
        snapshot_message = self._read_last_message(
            f"{part_of.meta_.stream_category}:snapshot-{identifier}"
        )

        position_in_snapshot: int = 0
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

    def _load_aggregate_at_version(
        self,
        part_of: Type[BaseAggregate],
        identifier: str,
        at_version: int,
    ) -> Optional[BaseAggregate]:
        """Load an aggregate at a specific version.

        Version is 0-indexed: version 0 = state after the first event.
        Snapshots are leveraged when the snapshot version <= ``at_version``.
        No new snapshots are created for temporal queries.
        """
        stream = f"{part_of.meta_.stream_category}-{identifier}"
        snapshot_message = self._read_last_message(
            f"{part_of.meta_.stream_category}:snapshot-{identifier}"
        )

        aggregate: Optional[BaseAggregate] = None

        if snapshot_message:
            snapshot_version: int = snapshot_message["data"].get("_version", -1)
            if snapshot_version <= at_version:
                # Snapshot is usable — initialize from it
                aggregate = part_of(**snapshot_message["data"])
                remaining = at_version - aggregate._version
                if remaining > 0:
                    event_stream = self._read(
                        stream,
                        position=aggregate._version + 1,
                        no_of_messages=remaining,
                    )
                    for event_message in event_stream:
                        event = Message.deserialize(event_message).to_domain_object()
                        aggregate._apply(event)
                # else: snapshot is exactly at the requested version

        if aggregate is None:
            # No usable snapshot — replay from the beginning
            event_stream = self._read(
                stream,
                no_of_messages=at_version + 1,
            )

            if not event_stream:
                return None

            events = [
                Message.deserialize(msg).to_domain_object() for msg in event_stream
            ]
            aggregate = part_of.from_events(events)

        # Validate we reached the requested version
        if aggregate._version < at_version:
            raise ObjectNotFoundError(
                f"`{part_of.__name__}` object with identifier {identifier} "
                f"does not have version {at_version}. "
                f"Latest version is {aggregate._version}."
            )

        return aggregate

    @staticmethod
    def _parse_event_time(raw_time: Any) -> datetime | None:
        """Normalise a raw ``time`` value from an event message to ``datetime``.

        Adapters may return the ``time`` field as either a ``datetime`` object
        (e.g. MessageDB via psycopg2) or as an ISO-8601 string (e.g. the
        memory adapter's ``to_dict()``).
        """
        if raw_time is None:
            return None
        if isinstance(raw_time, datetime):
            return raw_time
        if isinstance(raw_time, str):
            return datetime.fromisoformat(raw_time)
        return None

    @staticmethod
    def _make_comparable(
        event_time: datetime, cutoff: datetime
    ) -> tuple[datetime, datetime]:
        """Ensure both datetimes are comparable (both naive or both aware).

        MessageDB (PostgreSQL) returns timezone-naive timestamps stored as UTC,
        while the memory adapter stores ``datetime.now(UTC)`` which is
        timezone-aware.  When they differ, strip tzinfo from both sides so the
        comparison proceeds — all event store timestamps are treated as UTC.
        """
        event_aware = event_time.tzinfo is not None
        cutoff_aware = cutoff.tzinfo is not None

        if event_aware == cutoff_aware:
            return event_time, cutoff

        # Mixed: strip tzinfo from both (both are in UTC by convention)
        return event_time.replace(tzinfo=None), cutoff.replace(tzinfo=None)

    def _load_aggregate_as_of(
        self,
        part_of: Type[BaseAggregate],
        identifier: str,
        as_of: datetime,
    ) -> Optional[BaseAggregate]:
        """Load an aggregate as of a specific timestamp.

        Snapshots are skipped entirely — events are read from position 0 and
        filtered by their write timestamp.  Only events with
        ``time <= as_of`` are applied.
        """
        stream = f"{part_of.meta_.stream_category}-{identifier}"
        event_stream = self._read(stream)

        if not event_stream:
            return None

        # Filter events by write timestamp
        filtered_messages = []
        for msg in event_stream:
            event_time = self._parse_event_time(msg.get("time"))
            if event_time is not None:
                et, co = self._make_comparable(event_time, as_of)
                if et <= co:
                    filtered_messages.append(msg)

        if not filtered_messages:
            raise ObjectNotFoundError(
                f"`{part_of.__name__}` object with identifier {identifier} "
                f"has no events on or before {as_of}."
            )

        events = [
            Message.deserialize(msg).to_domain_object() for msg in filtered_messages
        ]
        aggregate = part_of.from_events(events)

        return aggregate

    def create_snapshot(self, part_of: Type[BaseAggregate], identifier: str) -> bool:
        """Create a snapshot for a specific event-sourced aggregate instance.

        Reads the full event stream for the aggregate, reconstructs it via
        ``from_events()``, and writes a snapshot to the snapshot stream.
        This bypasses the snapshot threshold -- manual triggers always create
        a snapshot regardless of event count.

        Args:
            part_of: The EventSourced Aggregate class
            identifier: Unique aggregate identifier

        Returns:
            True if a snapshot was created.

        Raises:
            IncorrectUsageError: If the aggregate is not event-sourced.
            ObjectNotFoundError: If no events exist for the given identifier.
        """
        if not part_of.meta_.is_event_sourced:
            raise IncorrectUsageError(
                f"`{part_of.__name__}` is not an event-sourced aggregate"
            )

        # Read ALL events (fresh reconstruction, not from existing snapshot)
        event_stream = deque(
            self._read(f"{part_of.meta_.stream_category}-{identifier}")
        )

        if not event_stream:
            raise ObjectNotFoundError(
                f"`{part_of.__name__}` object with identifier {identifier} "
                f"does not exist."
            )

        events = [Message.deserialize(msg).to_domain_object() for msg in event_stream]
        aggregate = part_of.from_events(events)

        self._write(
            f"{part_of.meta_.stream_category}:snapshot-{identifier}",
            "SNAPSHOT",
            aggregate.to_dict(),
        )

        return True

    @abstractmethod
    def _stream_identifiers(self, stream_category: str) -> List[str]:
        """Return all unique aggregate identifiers for a given stream category.

        Stream names follow the pattern ``{category}-{identifier}``.
        Snapshot streams (``{category}:snapshot-{identifier}``) must be
        excluded.

        Implemented by the concrete event store adapter.

        Args:
            stream_category: The stream category to scan (e.g. ``test::user``)

        Returns:
            Sorted list of unique aggregate identifiers.
        """

    def create_snapshots(self, part_of: Type[BaseAggregate]) -> int:
        """Create snapshots for all instances of an event-sourced aggregate.

        Discovers all unique aggregate identifiers in the stream category,
        then creates a snapshot for each.

        Args:
            part_of: The EventSourced Aggregate class

        Returns:
            Number of snapshots created.

        Raises:
            IncorrectUsageError: If the aggregate is not event-sourced.
        """
        if not part_of.meta_.is_event_sourced:
            raise IncorrectUsageError(
                f"`{part_of.__name__}` is not an event-sourced aggregate"
            )

        identifiers = self._stream_identifiers(part_of.meta_.stream_category)
        count = 0
        for identifier in identifiers:
            self.create_snapshot(part_of, identifier)
            count += 1

        return count

    @abstractmethod
    def _data_reset(self) -> None:
        """Flush all events.

        Useful for running tests with a clean slate.
        """

    def _last_event_of_type(
        self, event_cls: Type[BaseEvent], stream_category: str = None
    ) -> Optional[Union[BaseEvent, BaseCommand]]:
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
    ) -> List[Union[BaseEvent, BaseCommand]]:
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
