"""Module to test Elasticsearch Provider specific functionality"""

import pytest
from elasticsearch import Elasticsearch
from elasticsearch_dsl.response import Response

from protean import Domain
from protean.adapters.repository.elasticsearch import ESProvider
from protean.exceptions import ConfigurationError

from .elements import Alien, Person


@pytest.mark.elasticsearch
class TestElasticsearchProvider:
    """Test Elasticsearch-specific provider functionality"""

    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(Person)
        test_domain.register(Alien)
        test_domain.init(traverse=False)

    def test_provider_type_is_elasticsearch(self, test_domain):
        """Test that provider is of correct Elasticsearch type"""
        provider = test_domain.providers["default"]
        assert isinstance(provider, ESProvider)

    def test_provider_get_connection_returns_elasticsearch_client(self, test_domain):
        """Test that get_connection returns Elasticsearch client"""
        conn = test_domain.providers["default"].get_connection()
        assert conn is not None
        assert isinstance(conn, Elasticsearch)

    @pytest.mark.no_test_domain
    def test_exception_on_invalid_elasticsearch_provider(self):
        """Test exception on invalid Elasticsearch provider"""
        domain = Domain()
        domain.config["databases"]["default"] = {
            "provider": "elasticsearch",
            "database_uri": '{"hosts": ["imaginary"]}',
        }
        with pytest.raises(ConfigurationError) as exc:
            domain.init(traverse=False)

        assert "Could not connect to database at" in str(exc.value)

    @pytest.mark.pending
    def test_elasticsearch_raw_queries(self, test_domain):
        """Test Elasticsearch-specific raw queries"""
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

        # Filter by column value - Elasticsearch specific query format
        results = provider.raw("SELECT count(*) FROM person where last_name = 'John'")
        assert isinstance(results, Response)
        assert next(results)[0] == 2

        results = provider.raw(
            "SELECT count(*) FROM person where last_name = 'John' and age = 3"
        )
        assert next(results)[0] == 1

        # This query brings results from multiple repositories
        results = provider.raw("SELECT count(*) FROM person where age in (6,3)")
        assert next(results)[0] == 2

        results = provider.raw(
            "SELECT * FROM person where last_name = 'John' and age in (6,7)"
        )
        assert next(results)[0] == "Murdock"
