import importlib
import logging
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from protean.domain import Domain
    from protean.port.event_store import BaseEventStore

logger = logging.getLogger(__name__)

EVENT_STORE_PROVIDERS = {
    "memory": "protean.adapters.event_store.memory.MemoryEventStore",
    "message_db": "protean.adapters.event_store.message_db.MessageDBStore",
}


class EventStore:
    def __init__(self, domain: "Domain") -> None:
        self.domain: Domain = domain
        self._event_store: BaseEventStore | None = None

    @property
    def store(self) -> Optional["BaseEventStore"]:
        return self._event_store

    def close(self) -> None:
        """Close the event store and release all connections.

        Delegates to the inner store's close() without clearing the
        reference, so the wrapper remains usable (e.g., in test mode
        where the domain is still accessed after Engine.shutdown()).
        """
        if self._event_store is not None:
            self._event_store.close()
            logger.debug("Event store closed")

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

        store: BaseEventStore = event_store_cls(self.domain, configured_event_store)

        return store

    def _initialize(self) -> None:
        logger.debug("Initializing Event Store...")

        # Close any previously-initialized event store to release connections
        # before creating a new one (prevents connection pool exhaustion on
        # repeated domain.init() calls).
        if self._event_store is not None:
            self._event_store.close()

        # Initialize the Event Store
        #
        # An event store is always present by default. If not configured explicitly,
        #   a memory-based event store is used.
        self._event_store = self._initialize_event_store()
