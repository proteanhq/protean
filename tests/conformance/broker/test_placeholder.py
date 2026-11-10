"""A one-test placeholder that the broker port's conformance suite replaces."""

from protean.port.broker import BrokerCapabilities


def test_the_adapter_declares_broker_capabilities(adapter):
    assert isinstance(adapter.capabilities, BrokerCapabilities)
