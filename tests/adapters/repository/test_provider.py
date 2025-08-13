import pytest

from protean.adapters.repository import Providers


@pytest.mark.database
class TestBasicProvider:
    """Test basic provider functionality across SQLAlchemy databases"""

    def test_initialization_of_providers_on_first_call(self, test_domain):
        """Test that providers object is available"""
        assert isinstance(test_domain.providers, Providers)
        assert test_domain.providers._providers is not None
        assert "default" in test_domain.providers

    def test_connection_to_db_is_successful(self, test_domain):
        """Test connection to database"""
        provider = test_domain.providers["default"]
        assert provider.is_alive()

    def test_provider_name(self, test_domain):
        """Test that provider name is correctly set"""
        provider = test_domain.providers["default"]
        assert provider.name == "default"

    def test_provider_has_database_setting(self, test_domain):
        """Test that provider has a database setting"""
        provider = test_domain.providers["default"]
        assert hasattr(provider.__class__, "__database__")
        assert provider.__class__.__database__ is not None
