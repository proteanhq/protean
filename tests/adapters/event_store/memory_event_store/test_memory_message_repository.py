from protean.adapters.event_store.memory import MemoryMessage


def test_is_category(test_domain):
    test_domain.event_store.store  # Establish connection to event store
    repo = test_domain.repository_for(MemoryMessage)
    assert repo.is_category("testStream-123") is False
    assert repo.is_category("testStream") is True
    assert repo.is_category("test_stream-123") is False
    assert repo.is_category("") is False
