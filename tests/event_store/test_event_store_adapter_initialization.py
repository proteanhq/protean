import mock

from protean.port.event_store import BaseEventStore


def test_domain_event_store_attribute(test_domain):
    assert test_domain.event_store is not None
    assert isinstance(test_domain.event_store.store, BaseEventStore)


@mock.patch("protean.adapters.event_store.EventStore._initialize")
def test_event_store_initialization(mock_store_initialize, test_domain):
    test_domain._initialize()

    mock_store_initialize.assert_called_once()
