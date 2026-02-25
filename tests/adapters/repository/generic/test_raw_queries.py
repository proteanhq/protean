"""Generic raw query tests for providers with raw query support.

Tests raw query execution via the provider.raw() public interface.
The actual query syntax differs between providers (JSON for Memory,
SQL for SQLAlchemy), so these tests verify the capability gate works
rather than testing specific query syntax.
"""

import pytest

from protean.core.aggregate import BaseAggregate
from protean.exceptions import NotSupportedError
from protean.fields import Integer, String
from protean.port.provider import DatabaseCapabilities


class Person(BaseAggregate):
    first_name: String(max_length=50, required=True)
    last_name: String(max_length=50, required=True)
    age: Integer(default=21)


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Person)
    test_domain.init(traverse=False)


@pytest.mark.raw_queries
class TestRawQueries:
    """Test raw query execution across providers that support it."""

    def test_provider_declares_raw_queries_capability(self, test_domain):
        """Verify the provider has the RAW_QUERIES capability flag."""
        provider = test_domain.providers["default"]
        assert provider.has_capability(DatabaseCapabilities.RAW_QUERIES)

    def test_raw_does_not_raise_not_supported_error(self, test_domain):
        """Verify raw() does not raise NotSupportedError for capable providers."""
        # Create some data first
        test_domain.repository_for(Person)._dao.create(
            first_name="John", last_name="Doe", age=25
        )

        provider = test_domain.providers["default"]
        # Build a provider-appropriate query
        db_class = provider.__class__.__database__
        if db_class == "memory":
            query = '{"first_name": "John"}'
        else:
            # SQL providers
            query = "SELECT 1"

        # Should not raise NotSupportedError
        try:
            result = provider.raw(query)
        except NotSupportedError:
            pytest.fail(
                "raw() raised NotSupportedError on a RAW_QUERIES-capable provider"
            )
        assert result is not None
