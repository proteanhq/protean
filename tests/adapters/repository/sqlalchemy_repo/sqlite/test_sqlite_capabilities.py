"""Tests for SqliteProvider capability declarations."""

import pytest

from protean.port.provider import DatabaseCapabilities


@pytest.mark.sqlite
class TestSqliteProviderCapabilities:
    """Test SqliteProvider capability declaration and methods."""

    def test_capabilities(self, test_domain):
        provider = test_domain.providers["default"]

        assert provider.capabilities == DatabaseCapabilities.RELATIONAL

        assert provider.has_capability(DatabaseCapabilities.TRANSACTIONS)
        assert provider.has_capability(DatabaseCapabilities.SCHEMA_MANAGEMENT)
        assert provider.has_capability(DatabaseCapabilities.CONNECTION_POOLING)
        assert provider.has_capability(DatabaseCapabilities.RAW_QUERIES)

        assert not provider.has_capability(DatabaseCapabilities.NATIVE_JSON)
        assert not provider.has_capability(DatabaseCapabilities.NATIVE_ARRAY)
        assert not provider.has_capability(DatabaseCapabilities.SIMULATED_TRANSACTIONS)
