import mock

from protean.port import BaseEventStore


def test_domain_event_store_attribute(test_domain):
    assert test_domain.event_store is not None
    assert isinstance(test_domain.event_store.store, BaseEventStore)


@mock.patch("protean.adapters.event_store.EventStore._initialize")
def test_event_store_initialization(mock_store_initialize, test_domain):
    test_domain.event_store.store  # Initializes store if not initialized already

    mock_store_initialize.assert_called_once()
