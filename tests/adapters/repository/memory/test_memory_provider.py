"""Module to test Memory Provider specific functionality"""

import pytest

from protean.adapters.repository.memory import MemoryProvider
from protean.core.aggregate import _LegacyBaseAggregate as BaseAggregate
from protean.fields import Integer, String


class Person(BaseAggregate):
    first_name = String(max_length=50, required=True)
    last_name = String(max_length=50, required=True)
    age = Integer(default=21)


class Alien(BaseAggregate):
    first_name = String(max_length=50, required=True)
    last_name = String(max_length=50, required=True)
    age = Integer(default=21)


class TestMemoryProvider:
    """Test Memory-specific provider functionality"""

    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(Person)
        test_domain.register(Alien)

    def test_provider_type_is_memory(self, test_domain):
        """Test that provider is of correct Memory type"""
        provider = test_domain.providers["default"]
        assert isinstance(provider, MemoryProvider)

    def test_provider_get_connection_returns_memory_db(self, test_domain):
        """Test that get_connection returns memory database structure"""
        conn = test_domain.providers["default"].get_connection()
        assert all(key in conn._db for key in ["data", "lock", "counters"])

    def test_memory_raw_queries_with_json_format(self, test_domain):
        """Test Memory-specific raw queries with JSON format"""
        test_domain.repository_for(Person)._dao.create(
            first_name="Murdock", age=7, last_name="John"
        )
        test_domain.repository_for(Person)._dao.create(
            first_name="Jean", age=3, last_name="John"
        )
        test_domain.repository_for(Person)._dao.create(
            first_name="Bart", age=6, last_name="Carrie"
        )

        test_domain.repository_for(Alien)._dao.create(
            first_name="Sully", age=28, last_name="Monster"
        )
        test_domain.repository_for(Alien)._dao.create(
            first_name="Mike", age=26, last_name="Monster"
        )
        test_domain.repository_for(Alien)._dao.create(
            first_name="Boo", age=2, last_name="Human"
        )

        provider = test_domain.providers["default"]

        # Filter by attributes - Memory specific JSON format
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

    def test_memory_raw_query_json_decode_error(self, test_domain):
        """Test that malformed JSON in Memory raw query raises exception"""
        test_domain.repository_for(Person)._dao.create(
            first_name="Murdock", age=7, last_name="John"
        )

        provider = test_domain.providers["default"]

        # Malformed JSON with missing quotes around key
        with pytest.raises(Exception) as exc_info:
            provider.raw('{last_name:"John"}')

        assert "Query Malformed" in str(exc_info.value)

        # Malformed JSON with unclosed bracket
        with pytest.raises(Exception) as exc_info:
            provider.raw('{"last_name":"John"')

        assert "Query Malformed" in str(exc_info.value)

    def test_memory_raw_query_key_error(self, test_domain):
        """Test that querying with non-existent keys doesn't raise KeyError in Memory"""
        test_domain.repository_for(Person)._dao.create(
            first_name="Test", last_name="Person", age=30
        )

        provider = test_domain.providers["default"]

        # Query with non-existent field should return empty list without error
        results = provider.raw('{"non_existent_field":"value"}')
        assert isinstance(results, list)
        assert len(results) == 0

        # Query with mix of existing and non-existent fields
        results = provider.raw('{"last_name":"Person", "non_existent_field":"value"}')
        assert isinstance(results, list)
        assert len(results) == 0
