"""Module to test Elasticsearch Provider specific functionality"""

import pytest
from elasticsearch import Elasticsearch
from elasticsearch_dsl.response import Response

from protean import Domain
from protean.adapters.repository.elasticsearch import ESProvider
from protean.core.aggregate import BaseAggregate
from protean.core.entity import BaseEntity
from protean.exceptions import ConfigurationError
from protean.fields import HasMany, String

from .elements import Alien, Person

from tests.shared import initialize_domain


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

    def test_keyword_fields_precomputed_for_constructed_model(self, test_domain):
        """Test that keyword fields are precomputed and cached during model construction"""
        provider = test_domain.providers["default"]

        # Get the database model class for Person
        person_model_cls = provider.construct_database_model_class(Person)

        # Verify that keyword fields are cached
        assert hasattr(person_model_cls, "_keyword_fields")
        keyword_fields = person_model_cls._keyword_fields

        # String fields should be in keyword_fields
        assert "first_name" in keyword_fields
        assert "last_name" in keyword_fields

        # Numeric/date fields should NOT be in keyword_fields
        assert "age" not in keyword_fields  # Integer field
        assert "created_at" not in keyword_fields  # DateTime field
        assert "id" not in keyword_fields  # Identifier field

    def test_keyword_fields_cached_on_dao_database_model(self, test_domain):
        """Test that keyword fields are cached on DAO's database model class"""
        dao = test_domain.repository_for(Person)._dao

        # Verify that keyword fields are cached on the DAO's database model class
        assert hasattr(dao.database_model_cls, "_keyword_fields")
        keyword_fields = dao.database_model_cls._keyword_fields

        # Verify correct field classification
        assert "first_name" in keyword_fields  # String field
        assert "last_name" in keyword_fields  # String field
        assert "age" not in keyword_fields  # Integer field
        assert "created_at" not in keyword_fields  # DateTime field

    def test_compute_keyword_fields_method(self, test_domain):
        """Test the _compute_keyword_fields method directly"""
        provider = test_domain.providers["default"]

        # Test with Person entity (has String, Integer, DateTime fields)
        keyword_fields = provider._compute_keyword_fields(Person)

        # Should be a set
        assert isinstance(keyword_fields, set)

        # String fields should be included
        expected_string_fields = {"first_name", "last_name"}
        assert expected_string_fields.issubset(keyword_fields)

        # Non-string fields should be excluded
        non_string_fields = {"age", "created_at", "id"}
        assert not any(field in keyword_fields for field in non_string_fields)

    def test_keyword_fields_cached_across_dao_instances(self, test_domain):
        """Test that keyword fields are shared across DAO instances for same entity"""
        # Get two DAO instances for the same entity
        dao1 = test_domain.repository_for(Person)._dao
        dao2 = test_domain.repository_for(Person)._dao

        # Both should have the same cached keyword fields
        assert hasattr(dao1.database_model_cls, "_keyword_fields")
        assert hasattr(dao2.database_model_cls, "_keyword_fields")

        # Should be the same object (cached)
        assert (
            dao1.database_model_cls._keyword_fields
            is dao2.database_model_cls._keyword_fields
        )


class ESOrder(BaseAggregate):
    name: String(required=True)
    items = HasMany("ESLineItem")


class ESLineItem(BaseEntity):
    sku: String(required=True)


@pytest.mark.elasticsearch
@pytest.mark.no_test_domain
class TestCreateArtifactsEventSourcedFilter:
    """Test that _create_database_artifacts skips event-sourced aggregates."""

    def test_create_artifacts_skips_event_sourced_aggregates(self):
        """Event-sourced aggregates use the event store, not ES indices.
        _create_database_artifacts should skip them and their child entities."""
        domain = initialize_domain(name="ES-EventSourced-Test", root_path=__file__)

        # Register a regular aggregate and an event-sourced aggregate with entity
        domain.register(Person)
        domain.register(ESOrder, is_event_sourced=True)
        domain.register(ESLineItem, part_of=ESOrder)
        domain.init(traverse=False)

        with domain.domain_context():
            provider = domain.providers["default"]
            conn = provider.get_connection()

            try:
                provider._create_database_artifacts()

                # Person (regular aggregate) should have its index created
                person_model = domain.repository_for(Person)._database_model
                assert conn.indices.exists(index=person_model._index._name)

                # Event-sourced aggregate should NOT have an index
                es_order_schema = provider.namespaced_schema_name("es_order")
                assert not conn.indices.exists(index=es_order_schema)

                # Entity of event-sourced aggregate should NOT have an index
                es_line_item_schema = provider.namespaced_schema_name("es_line_item")
                assert not conn.indices.exists(index=es_line_item_schema)
            finally:
                provider._drop_database_artifacts()
