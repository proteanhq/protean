"""Tests for Provider Functionality"""
from protean.core.provider import providers
from protean.impl.repository.dict_repo import DictProvider


class TestProviders:
    """This class holds tests for Providers Singleton"""

    def test_init(self):
        """Test that ``providers`` object is available"""
        assert providers is not None

    def test_provider_detail(self):
        """Test provider info loaded for tests"""

        provider1 = providers.get_provider('default')
        assert isinstance(provider1, DictProvider)

    def test_provider_get_connection(self):
        """Test ``get_connection`` method and check for connection details"""

        conn = providers.get_provider('default').get_connection()
        assert all(key in conn for key in ['data', 'lock', 'counters'])
