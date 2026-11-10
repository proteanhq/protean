"""A one-test placeholder that the event store port's conformance suite replaces."""

from protean.port.event_store import EventStoreCapabilities


def test_the_adapter_declares_event_store_capabilities(adapter):
    assert isinstance(adapter.capabilities, EventStoreCapabilities)
