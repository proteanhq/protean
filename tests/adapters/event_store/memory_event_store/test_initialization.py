from protean.adapters.event_store.memory import MemoryEventStore
from protean.port.event_store import BaseEventStore


def test_retrieving_message_store_from_domain(test_domain):
    assert test_domain.event_store is not None
    assert test_domain.event_store.store is not None

    assert isinstance(test_domain.event_store.store, BaseEventStore)
    assert isinstance(test_domain.event_store.store, MemoryEventStore)
