"""A one-test placeholder that the database port's conformance suite replaces."""

from protean.port.database import DatabaseCapabilities


def test_the_adapter_declares_database_capabilities(adapter):
    assert isinstance(adapter.capabilities, DatabaseCapabilities)
