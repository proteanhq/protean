"""Tests for ESProvider capability declarations."""

import pytest

from protean.port.provider import DatabaseCapabilities


@pytest.mark.elasticsearch
class TestESProviderCapabilities:
    """Test ESProvider capability declaration and methods."""

    def test_capabilities(self, test_domain):
        provider = test_domain.providers["default"]

        assert provider.capabilities == DatabaseCapabilities.DOCUMENT_STORE

        assert provider.has_capability(DatabaseCapabilities.CRUD)
        assert provider.has_capability(DatabaseCapabilities.SCHEMA_MANAGEMENT)
        assert provider.has_capability(DatabaseCapabilities.OPTIMISTIC_LOCKING)

        assert not provider.has_capability(DatabaseCapabilities.TRANSACTIONS)
        assert not provider.has_capability(DatabaseCapabilities.SIMULATED_TRANSACTIONS)
        assert not provider.has_capability(DatabaseCapabilities.RAW_QUERIES)
        assert not provider.has_capability(DatabaseCapabilities.CONNECTION_POOLING)
