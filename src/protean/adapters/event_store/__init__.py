import importlib
import logging

from collections import defaultdict
from typing import List, Optional

from protean import BaseEvent, BaseEventHandler
from protean.core.command import BaseCommand
from protean.core.command_handler import BaseCommandHandler
from protean.core.event_sourced_repository import (
    BaseEventSourcedRepository,
    event_sourced_repository_factory,
)
from protean.exceptions import ConfigurationError, NotSupportedError
from protean.utils import fqn

logger = logging.getLogger(__name__)


class EventStore:
    def __init__(self, domain):
        self.domain = domain
        self._event_store = None
        self._event_streams = None
        self._command_streams = None

    @property
    def store(self):
        if self._event_store is None:
            self._initialize()

        return self._event_store

    def _initialize(self):
        if not self._event_store:
            logger.debug("Initializing Event Store...")

            configured_event_store = self.domain.config["EVENT_STORE"]
            if configured_event_store and isinstance(configured_event_store, dict):
                event_store_full_path = configured_event_store["PROVIDER"]
                event_store_module, event_store_class = event_store_full_path.rsplit(
                    ".", maxsplit=1
                )

                event_store_cls = getattr(
                    importlib.import_module(event_store_module), event_store_class
                )

                store = event_store_cls(self.domain, configured_event_store)
            else:
                raise ConfigurationError(
                    "Configure at least one event store in the domain"
                )

            self._event_store = store

            self._initialize_event_streams()
            self._initialize_command_streams()

        return self._event_store

    def _initialize_event_streams(self):
        self._event_streams = defaultdict(set)

        for _, record in self.domain.registry.event_handlers.items():
            stream_name = (
                record.cls.meta_.stream_name
                or record.cls.meta_.aggregate_cls.meta_.stream_name
            )
            self._event_streams[stream_name].add(record.cls)

    def _initialize_command_streams(self):
        self._command_streams = defaultdict(set)

        for _, record in self.domain.registry.command_handlers.items():
            self._command_streams[record.cls.meta_.aggregate_cls.meta_.stream_name].add(
                record.cls
            )

    def repository_for(self, aggregate_cls):
        if self._event_store is None:
            self._initialize()

        repository_cls = type(
            aggregate_cls.__name__ + "Repository", (BaseEventSourcedRepository,), {}
        )
        repository_cls = event_sourced_repository_factory(
            repository_cls, aggregate_cls=aggregate_cls
        )
        return repository_cls(self.domain)

    def handlers_for(self, event: BaseEvent) -> List[BaseEventHandler]:
        if self._event_streams is None:
            self._initialize_event_streams()

        all_stream_handlers = self._event_streams.get("$all", set())

        stream_name = (
            event.meta_.stream_name or event.meta_.aggregate_cls.meta_.stream_name
        )
        stream_handlers = self._event_streams.get(stream_name, set())

        return set.union(stream_handlers, all_stream_handlers)

    def command_handler_for(self, command: BaseCommand) -> Optional[BaseCommandHandler]:
        if self._command_streams is None:
            self._initialize_command_streams()

        stream_name = command.meta_.stream_name or (
            command.meta_.aggregate_cls.meta_.stream_name
            if command.meta_.aggregate_cls
            else None
        )

        if not stream_name:
            return None

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
