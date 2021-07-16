import pytest

from protean.adapters.repository import Providers
from protean.adapters.repository.memory import MemoryProvider

from .elements import Alien, Person


class TestProviders:
    """This class holds tests for Providers Singleton"""

    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(Person)
        test_domain.register(Alien)

    def test_initialization_of_providers_on_first_call(self, test_domain):
        """Test that ``providers`` object is available"""
        assert isinstance(test_domain.providers, Providers)
        assert test_domain.providers._providers is None

        test_domain.get_provider("default")
        assert test_domain.providers is not None

    def test_provider_detail(self, test_domain):
        """Test provider info loaded for tests"""

        provider1 = test_domain.get_provider("default")
        assert isinstance(provider1, MemoryProvider)

    def test_provider_get_connection(self, test_domain):
        """Test ``get_connection`` method and check for connection details"""

        conn = test_domain.get_provider("default").get_connection()
        assert all(key in conn._db for key in ["data", "lock", "counters"])

    def test_provider_raw(self, test_domain):
        """Test raw queries"""
        test_domain.get_dao(Person).create(
            first_name="Murdock", age=7, last_name="John"
        )
        test_domain.get_dao(Person).create(first_name="Jean", age=3, last_name="John")
        test_domain.get_dao(Person).create(first_name="Bart", age=6, last_name="Carrie")

        test_domain.get_dao(Alien).create(
            first_name="Sully", age=28, last_name="Monster"
        )
        test_domain.get_dao(Alien).create(
            first_name="Mike", age=26, last_name="Monster"
        )
        test_domain.get_dao(Alien).create(first_name="Boo", age=2, last_name="Human")

        provider = test_domain.get_provider("default")

        # Filter by Dog attributes
        results = provider.raw('{"last_name":"John"}')
        assert isinstance(results, list)
        assert len(results) == 2

        # Try with single quotes in JSON String
        results = provider.raw("{'last_name':'John'}")
        assert len(results) == 2

        results = provider.raw('{"last_name":"John", "age":3}')
        assert len(results) == 1

        # This query brings results from multiple repositories
        results = provider.raw('{"age__in":[2, 3]}')
        assert len(results) == 2

        results = provider.raw('{"last_name":"John", "age__in":[6,7]}')
        assert len(results) == 1

        results = provider.raw('{"last_name":"John", "age__in":[2, 3,7]}')
        assert len(results) == 2
