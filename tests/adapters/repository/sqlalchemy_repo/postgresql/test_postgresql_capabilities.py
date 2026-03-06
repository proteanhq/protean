"""Tests for PostgresqlProvider capability declarations."""

import pytest

from protean.port.provider import DatabaseCapabilities


@pytest.mark.postgresql
class TestPostgresqlProviderCapabilities:
    """Test PostgresqlProvider capability declaration and methods."""

    def test_capabilities(self, test_domain):
        provider = test_domain.providers["default"]

        expected = (
            DatabaseCapabilities.RELATIONAL
            | DatabaseCapabilities.NATIVE_JSON
            | DatabaseCapabilities.NATIVE_ARRAY
        )
        assert provider.capabilities == expected

        assert provider.has_capability(DatabaseCapabilities.TRANSACTIONS)
        assert provider.has_capability(DatabaseCapabilities.NATIVE_JSON)
        assert provider.has_capability(DatabaseCapabilities.NATIVE_ARRAY)
        assert provider.has_capability(DatabaseCapabilities.SCHEMA_MANAGEMENT)
        assert provider.has_capability(DatabaseCapabilities.CONNECTION_POOLING)
        assert provider.has_capability(DatabaseCapabilities.RAW_QUERIES)
        assert provider.has_capability(DatabaseCapabilities.OPTIMISTIC_LOCKING)

        assert not provider.has_capability(DatabaseCapabilities.SIMULATED_TRANSACTIONS)
