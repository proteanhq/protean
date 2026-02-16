import importlib
import logging
from collections import defaultdict
from typing import TYPE_CHECKING, Any, DefaultDict, Optional, Set

from protean.core.command_handler import BaseCommandHandler
from protean.core.event_handler import BaseEventHandler
from protean.core.event_sourced_repository import (
    BaseEventSourcedRepository,
    event_sourced_repository_factory,
)
from protean.core.projector import BaseProjector
from protean.exceptions import ConfigurationError, NotSupportedError
from protean.utils import fqn

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
        self.domain: "Domain" = domain
        self._event_store: "BaseEventStore" = None
        self._event_streams: DefaultDict[str, Set[BaseEventHandler]] = defaultdict(set)
        self._command_streams: DefaultDict[str, Set[BaseCommandHandler]] = defaultdict(
            set
        )
        self._projectors: DefaultDict[str, Set[BaseProjector]] = defaultdict(set)

    @property
    def store(self):
        return self._event_store

    def _initialize_event_store(self) -> "BaseEventStore":
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
            stream_category = (
                record.cls.meta_.stream_category
                or record.cls.meta_.part_of.meta_.stream_category
            )
            self._event_streams[stream_category].add(record.cls)

        for _, record in self.domain.registry.projectors.items():
            for stream_category in record.cls.meta_.stream_categories:
                self._event_streams[stream_category].add(record.cls)
                self._projectors[fqn(record.cls.meta_.projector_for)].add(record.cls)

    def _initialize_command_streams(self):
        for _, record in self.domain.registry.command_handlers.items():
            self._command_streams[record.cls.meta_.part_of.meta_.stream_category].add(
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

    def handlers_for(self, event: Any) -> set:
        """Return all handlers configured to run on the given event."""
        # Gather handlers configured to run on all events
        all_stream_handlers = self._event_streams.get("$all", set())

        # Gather all handlers configured to run on this event
        stream_handlers = self._event_streams.get(
            event.meta_.part_of.meta_.stream_category, set()
        )
        configured_stream_handlers = set()
        for stream_handler in stream_handlers:
            if event.__class__.__type__ in stream_handler._handlers:
                configured_stream_handlers.add(stream_handler)

        return set.union(configured_stream_handlers, all_stream_handlers)

    def projectors_for(self, projection_cls) -> set:
        """Return Projectors listening to a specific projection

        Args:
            projection_cls (BaseProjection): Projection to be consumed

        Returns:
            List[BaseProjector]: Projectors that have registered to consume the projection
        """
        return self._projectors.get(fqn(projection_cls), set())

    def command_handler_for(self, command: Any) -> Optional[BaseCommandHandler]:
        if not command.meta_.part_of:
            raise ConfigurationError(
                f"Command `{command.__name__}` needs to be associated with an aggregate"
            )

        stream_category = command.meta_.part_of.meta_.stream_category

        handler_classes = self._command_streams.get(stream_category, set())

        # No command handlers have been configured to run this command
        if len(handler_classes) == 0:
            return None

        # Ensure that a command has a unique handler across all handlers
        # FIXME Perform this check on domain spin-up?
        handler_methods = set()
        for handler_cls in handler_classes:
            try:
                handler_method = next(
                    iter(handler_cls._handlers[command.__class__.__type__])
                )
                handler_methods.add((handler_cls, handler_method))
            except StopIteration:
                pass

        if len(handler_methods) > 1:
            raise NotSupportedError(
                f"Command {command.__class__.__name__} cannot be handled by multiple handlers"
            )

        return next(iter(handler_methods))[0] if handler_methods else None
