# --8<-- [start:class]
from collections.abc import Mapping
from typing import Any

from protean import Domain
from protean.adapters.event_store.memory import MemoryEventStore
from protean.infra.registry import event_stores
from protean.port.event_store import (
    EventStoreCapabilities,
    EventStoreHealth,
    EventStorePort,
    RawMessage,
)


class DelegatingEventStore(EventStorePort):
    """An event store that hands every operation to the memory event store.

    Replace the delegate calls with calls to your store's client.
    """

    def __init__(self, name: str, domain: "Domain", config: Mapping[str, Any]) -> None:
        self.name = name
        self.domain = domain
        self.config = config
        # Open your store's client here
        self._delegate = MemoryEventStore(name, domain, config)

    @property
    def capabilities(self) -> EventStoreCapabilities:
        """Declare only the guarantees the store makes."""
        return self._delegate.capabilities

    # Writing
    def write_message(
        self,
        stream_name: str,
        message_type: str,
        data: Mapping[str, Any],
        metadata: Mapping[str, Any] | None = None,
        expected_version: int | None = None,
    ) -> int:
        return self._delegate.write_message(
            stream_name, message_type, data, metadata, expected_version
        )

    # Reading
    def get_stream_messages(
        self, stream_name: str, position: int = 0, limit: int = 1000
    ) -> list[RawMessage]:
        return self._delegate.get_stream_messages(stream_name, position, limit)

    def get_category_messages(
        self,
        category: str,
        position: int = 0,
        limit: int = 1000,
        *,
        consumer_group_member: int | None = None,
        consumer_group_size: int | None = None,
    ) -> list[RawMessage]:
        return self._delegate.get_category_messages(
            category,
            position,
            limit,
            consumer_group_member=consumer_group_member,
            consumer_group_size=consumer_group_size,
        )

    def get_all_messages(
        self, position: int = 0, limit: int = 1000
    ) -> list[RawMessage]:
        return self._delegate.get_all_messages(position, limit)

    def stream_ids(self, category: str) -> list[str]:
        return self._delegate.stream_ids(category)

    # Last message
    def get_last_stream_message(self, stream_name: str) -> RawMessage | None:
        return self._delegate.get_last_stream_message(stream_name)

    def get_last_category_message(self, category: str) -> RawMessage | None:
        return self._delegate.get_last_category_message(category)

    def get_last_message(self) -> RawMessage | None:
        return self._delegate.get_last_message()

    # Connection and health
    def ping(self) -> bool:
        return self._delegate.ping()

    def health(self) -> EventStoreHealth:
        return self._delegate.health()

    def get_connection(self) -> object:
        return self._delegate.get_connection()

    def close(self) -> None:
        self._delegate.close()

    # Test harness
    def clear(self) -> None:
        self._delegate.clear()


# --8<-- [end:class]


# --8<-- [start:port-check]
_PORT_CHECK: type[EventStorePort] = DelegatingEventStore
# --8<-- [end:port-check]


# --8<-- [start:register]
def register() -> None:
    """Register the store as `provider = "delegating_memory"`."""
    event_stores.register("delegating_memory", f"{__name__}.DelegatingEventStore")


register()
# --8<-- [end:register]
