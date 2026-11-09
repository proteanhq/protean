import logging
from collections import defaultdict
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Optional, cast

from protean.core.command_handler import BaseCommandHandler
from protean.core.event_handler import BaseEventHandler
from protean.core.event_sourced_repository import (
    BaseEventSourcedRepository,
    event_sourced_repository_factory,
)
from protean.core.projector import BaseProjector
from protean.exceptions import ConfigurationError
from protean.infra.registry import event_stores as event_store_registry
from protean.utils import fqn

if TYPE_CHECKING:
    from protean.domain import Domain
    from protean.port.event_store import BaseEventStore

logger = logging.getLogger(__name__)


def register_message_db() -> None:
    """Register MessageDBStore with Protean as the `message_db` event store."""
    # Lives here, away from message_db.py, so that registering the name does not
    # import psycopg2. Without the extra installed, `get("message_db")` then
    # fails naming the missing module instead of reporting an unknown name.
    event_store_registry.register(
        "message_db", "protean.adapters.event_store.message_db.MessageDBStore"
    )


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
        # Event store adapters take (domain, conn_info) and pass their own name
        # to BaseEventStore, so the base constructor does not describe them.
        event_store_cls = cast(
            "Callable[[Domain, dict[str, Any]], BaseEventStore]",
            event_store_registry.get(configured_event_store["provider"]),
        )
        return event_store_cls(self.domain, configured_event_store)

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
