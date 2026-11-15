from protean import Domain
from protean.adapters.event_store.memory import MemoryEventStore
from protean.port.event_store import BaseEventStore


def test_retrieving_message_store_from_domain(test_domain):
    assert test_domain.event_store is not None
    assert test_domain.event_store.store is not None

    assert isinstance(test_domain.event_store.store, BaseEventStore)
    assert isinstance(test_domain.event_store.store, MemoryEventStore)


def test_memory_event_store_registers_no_domain_element():
    domain = Domain(name="MemoryStoreRegistry")

    @domain.aggregate
    class Account:
        pass

    domain.init(traverse=False)

    assert isinstance(domain.event_store.store, MemoryEventStore)
    # Read the raw records: the public views hide internal elements.
    records = [
        record
        for by_name in domain._domain_registry._elements.values()
        for record in by_name.values()
    ]
    assert "Account" in [record.name for record in records]
    assert [
        record.qualname
        for record in records
        if record.cls.__module__.startswith("protean.adapters.event_store")
    ] == []
