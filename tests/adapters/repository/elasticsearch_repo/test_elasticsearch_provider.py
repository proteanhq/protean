"""Module to test Elasticsearch Provider specific functionality"""

import pytest
from elasticsearch import Elasticsearch

from protean import Domain
from protean.adapters.repository.elasticsearch import ESProvider
from protean.core.aggregate import BaseAggregate
from protean.core.entity import BaseEntity
from protean.core.projection import BaseProjection
from protean.exceptions import ConfigurationError, NotSupportedError
from protean.fields import HasMany, Identifier, Integer, String
from tests.shared import initialize_domain

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
            "database_uri": '{"hosts": ["imaginary:abc"]}',
        }
        with pytest.raises(ConfigurationError) as exc:
            domain.init(traverse=False)

        assert "Invalid Elasticsearch connection configuration" in str(exc.value)
        # The host configuration (which may carry credentials) must not leak
        # into the error message.
        assert "imaginary" not in str(exc.value)

    def test_elasticsearch_raw_query_raises_not_supported(self, test_domain):
        """Elasticsearch does not support raw queries — both provider.raw() and
        QuerySet.raw() should raise NotSupportedError."""
        provider = test_domain.providers["default"]

        # Provider-level gate
        with pytest.raises(NotSupportedError, match="does not support raw queries"):
            provider.raw("SELECT * FROM person")

        # QuerySet-level gate
        with pytest.raises(NotSupportedError, match="does not support raw queries"):
            test_domain.repository_for(Person)._dao.query.raw("SELECT * FROM person")

    def test_keyword_fields_precomputed_for_constructed_model(self, test_domain):
        """Test that keyword fields are precomputed and cached during model construction.

        With explicit Keyword mappings, auto-generated models have no fields
        needing .keyword suffix (all strings are Keyword type natively).
        """
        provider = test_domain.providers["default"]

        # Get the database model class for Person
        person_model_cls = provider.construct_database_model_class(Person)

        # Verify that keyword fields are cached
        assert hasattr(person_model_cls, "_keyword_fields")
        keyword_fields = person_model_cls._keyword_fields

        # With explicit Keyword mapping, no fields need .keyword subfield
        assert keyword_fields == set()

    def test_keyword_fields_cached_on_dao_database_model(self, test_domain):
        """Test that keyword fields are cached on DAO's database model class"""
        dao = test_domain.repository_for(Person)._dao

        # Verify that keyword fields are cached on the DAO's database model class
        assert hasattr(dao.database_model_cls, "_keyword_fields")
        keyword_fields = dao.database_model_cls._keyword_fields

        # With explicit Keyword mapping, auto-generated models have empty set
        assert keyword_fields == set()

    def test_compute_keyword_fields_method(self, test_domain):
        """Test the _compute_keyword_fields method directly"""
        provider = test_domain.providers["default"]

        # Test with Person entity (has String, Integer, DateTime fields)
        # Without custom attrs, all fields are auto-mapped as Keyword (no .keyword needed)
        keyword_fields = provider._compute_keyword_fields(Person)

        # Should be a set
        assert isinstance(keyword_fields, set)

        # With explicit Keyword mapping, no fields need .keyword subfield
        assert keyword_fields == set()

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


class CacheLeaderboard(BaseProjection):
    entry_id: Identifier(identifier=True)
    score: Integer()


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
        domain.register(ESOrder, event_sourced=True)
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


@pytest.mark.elasticsearch
@pytest.mark.no_test_domain
class TestCreateArtifactsCacheBackedProjectionFilter:
    """Test that _create_database_artifacts skips cache-backed projections."""

    def test_create_artifacts_skips_cache_backed_projection(self):
        """A cache-backed projection carries ``meta_.provider is None``. Before the
        consolidation onto ``BaseProvider.owns()``, the Elasticsearch index loops
        resolved ``providers[None]`` unconditionally and raised ``KeyError``,
        breaking index setup for the whole domain (an analogue of the break
        fixed for SQLAlchemy). Index setup must skip it and succeed for the real
        aggregate."""
        domain = initialize_domain(name="ES-Cache-Projection-Test", root_path=__file__)

        domain.register(Person)
        domain.register(CacheLeaderboard, cache="default")
        domain.init(traverse=False)

        with domain.domain_context():
            provider = domain.providers["default"]
            conn = provider.get_connection()

            try:
                # Must not raise on the cache projection's ``None`` provider.
                provider._create_database_artifacts()

                # Person (regular aggregate) should have its index created
                person_model = domain.repository_for(Person)._database_model
                assert conn.indices.exists(index=person_model._index._name)

                # Cache-backed projection should NOT have an index
                leaderboard_schema = provider.namespaced_schema_name(
                    CacheLeaderboard.meta_.schema_name
                )
                assert not conn.indices.exists(index=leaderboard_schema)

                # Data reset applies the same ownership gate: it must skip the
                # cache-backed projection (no index to clear) and complete
                # without raising for the owned aggregate.
                provider._data_reset()
                assert conn.indices.exists(index=person_model._index._name)
            finally:
                provider._drop_database_artifacts()


def _base_urls(hosts, **options):
    """Build an ``ESProvider`` for ``hosts`` and return its client's node base URLs.

    Building the provider creates the client and opens no connection.
    """
    conn_info = {
        "provider": "elasticsearch",
        "database_uri": {"hosts": hosts},
        **options,
    }
    provider = ESProvider("default", Domain(), conn_info)
    return [node.base_url for node in provider._client.transport.node_pool.all()]


@pytest.mark.elasticsearch
@pytest.mark.no_test_domain
class TestElasticsearchHostNormalization:
    @pytest.mark.parametrize(
        "host, base_url",
        [
            ("localhost", "http://localhost:9200"),
            ("localhost:9201", "http://localhost:9201"),
            ("http://es", "http://es:9200"),
            ("http://es:9200", "http://es:9200"),
            ("http://[::1]", "http://[::1]:9200"),
            ("http://[::1]:9201", "http://[::1]:9201"),
        ],
    )
    def test_string_host_gets_a_scheme_and_a_port(self, host, base_url):
        assert _base_urls([host]) == [base_url]

    def test_https_url_without_a_port_keeps_the_client_default(self):
        # The client gives an https URL without a port port 443, which hosted
        # services such as Elastic Cloud listen on.
        assert _base_urls(["https://es"]) == ["https://es:443"]

    def test_bare_host_with_use_ssl_gets_https_and_port_9200(self):
        assert _base_urls(["localhost"], USE_SSL=True) == ["https://localhost:9200"]

    def test_credentials_are_kept_when_the_port_is_added(self):
        conn_info = {
            "provider": "elasticsearch",
            "database_uri": {"hosts": ["http://elastic:secret@es"]},
        }
        provider = ESProvider("default", Domain(), conn_info)

        [node] = provider._client.transport.node_pool.all()
        # The client moves the credentials into an authorization header.
        assert node.base_url == "http://es:9200"
        assert node.config.headers["authorization"].startswith("Basic ")

    def test_dict_host_is_passed_unchanged(self):
        host = {"host": "es", "port": 9201, "scheme": "http"}

        assert _base_urls([host]) == ["http://es:9201"]

    def test_non_numeric_port_is_left_for_the_client_to_reject(self):
        with pytest.raises(ConfigurationError) as exc:
            _base_urls(["http://elastic:secret@imaginary:abc"])

        assert "Invalid Elasticsearch connection configuration" in str(exc.value)
        assert "imaginary" not in str(exc.value)
        assert "secret" not in str(exc.value)
