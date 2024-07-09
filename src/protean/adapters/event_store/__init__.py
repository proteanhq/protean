from __future__ import annotations

import importlib
import logging
from collections import defaultdict
from typing import TYPE_CHECKING, DefaultDict, List, Optional, Set, Type

from protean import BaseEvent, BaseEventHandler
from protean.core.command import BaseCommand
from protean.core.command_handler import BaseCommandHandler
from protean.core.event_sourced_repository import (
    BaseEventSourcedRepository,
    event_sourced_repository_factory,
)
from protean.exceptions import ConfigurationError, NotSupportedError
from protean.utils import fqn
from protean.utils.mixins import Message

if TYPE_CHECKING:
    from protean.domain import Domain
    from protean.port.event_store import BaseEventStore

logger = logging.getLogger(__name__)

EVENT_STORE_PROVIDERS = {
    "memory": "protean.adapters.event_store.memory.MemoryEventStore",
    "message_db": "protean.adapters.event_store.message_db.MessageDBStore",
}


class EventStore:
    def __init__(self, domain):
        self.domain: Domain = domain
        self._event_store: BaseEventStore = None
        self._event_streams: DefaultDict[str, Set[BaseEventHandler]] = defaultdict(set)
        self._command_streams: DefaultDict[str, Set[BaseCommandHandler]] = defaultdict(
            set
        )

    @property
    def store(self):
        return self._event_store

    def _initialize_event_store(self) -> BaseEventStore:
        configured_event_store = self.domain.config["event_store"]
        event_store_full_path = EVENT_STORE_PROVIDERS[
            configured_event_store["provider"]
        ]
        event_store_module, event_store_class = event_store_full_path.rsplit(
            ".", maxsplit=1
        )

        event_store_cls = getattr(
            importlib.import_module(event_store_module), event_store_class
        )

        store = event_store_cls(self.domain, configured_event_store)

        return store

    def _initialize(self) -> None:
        logger.debug("Initializing Event Store...")

        # Initialize the Event Store
        #
        # An event store is always present by default. If not configured explicitly,
        #   a memory-based event store is used.
        self._event_store = self._initialize_event_store()

        self._initialize_event_streams()
        self._initialize_command_streams()

    def _initialize_event_streams(self):
        for _, record in self.domain.registry.event_handlers.items():
            stream_name = (
                record.cls.meta_.stream_name
                or record.cls.meta_.part_of.meta_.stream_name
            )
            self._event_streams[stream_name].add(record.cls)

    def _initialize_command_streams(self):
        for _, record in self.domain.registry.command_handlers.items():
            self._command_streams[record.cls.meta_.part_of.meta_.stream_name].add(
                record.cls
            )

    def repository_for(self, part_of):
        repository_cls = type(
            part_of.__name__ + "Repository", (BaseEventSourcedRepository,), {}
        )
        repository_cls = event_sourced_repository_factory(
            repository_cls, self.domain, part_of=part_of
        )
        return repository_cls(self.domain)

    def handlers_for(self, event: BaseEvent) -> List[BaseEventHandler]:
        """Return all handlers configured to run on the given event."""
        # Gather handlers configured to run on all events
        all_stream_handlers = self._event_streams.get("$all", set())

        # Gather all handlers configured to run on this event
        stream_handlers = self._event_streams.get(
            event.meta_.part_of.meta_.stream_name, set()
        )
        configured_stream_handlers = set()
        for stream_handler in stream_handlers:
            if fqn(event.__class__) in stream_handler._handlers:
                configured_stream_handlers.add(stream_handler)

        return set.union(configured_stream_handlers, all_stream_handlers)

    def command_handler_for(self, command: BaseCommand) -> Optional[BaseCommandHandler]:
        if not command.meta_.part_of:
            raise ConfigurationError(
                f"Command `{command.__name__}` needs to be associated with an aggregate"
            )

        stream_name = command.meta_.part_of.meta_.stream_name

        handler_classes = self._command_streams.get(stream_name, set())

        # No command handlers have been configured to run this command
        if len(handler_classes) == 0:
            return None

        # Ensure that a command has a unique handler across all handlers
        # FIXME Perform this check on domain spin-up?
        handler_methods = set()
        for handler_cls in handler_classes:
            try:
                handler_method = next(
                    iter(handler_cls._handlers[fqn(command.__class__)])
                )
                handler_methods.add((handler_cls, handler_method))
            except StopIteration:
                pass

        if len(handler_methods) > 1:
            raise NotSupportedError(
                f"Command {command.__class__.__name__} cannot be handled by multiple handlers"
            )

        return next(iter(handler_methods))[0] if handler_methods else None

    def last_event_of_type(
        self, event_cls: Type[BaseEvent], stream_name: str = None
    ) -> BaseEvent:
        stream_name = stream_name or "$all"
        events = [
            event
            for event in self.domain.event_store.store._read(stream_name)
            if event["type"] == fqn(event_cls)
        ]

        return Message.from_dict(events[-1]).to_object() if len(events) > 0 else None

    def events_of_type(
        self, event_cls: Type[BaseEvent], stream_name: str = None
    ) -> List[BaseEvent]:
        """Read events of a specific type in a given stream.

        This is a utility method, especially useful for testing purposes, that retrives events of a
        specific type from the event store.

        If no stream is specified, events of the requested type will be retrieved from all streams.

        :param event_cls: Class of the event type to be retrieved
        :param stream_name: Stream from which events are to be retrieved
        :type event_cls: BaseEvent Class
        :type stream_name: String, optional, default is `None`
        :return: A list of events of `event_cls` type
        :rtype: list
        """
        stream_name = stream_name or "$all"
        return [
            Message.from_dict(event).to_object()
            for event in self.domain.event_store.store._read(stream_name)
            if event["type"] == fqn(event_cls)
        ]
