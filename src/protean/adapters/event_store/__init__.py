import importlib
import logging

from protean.core.event_sourced_repository import (
    BaseEventSourcedRepository,
    event_sourced_repository_factory,
)
from protean.exceptions import ConfigurationError

logger = logging.getLogger(__name__)


class EventStore:
    def __init__(self, domain):
        self.domain = domain
        self._event_store = None

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

                store = event_store_cls(self, configured_event_store)
            else:
                raise ConfigurationError(
                    "Configure at least one event store in the domain"
                )

            self._event_store = store

        return self._event_store

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
