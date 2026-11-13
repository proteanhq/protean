"""The example on the production configuration guide behaves as the page says."""

import pytest

from protean.adapters.repository.elasticsearch import ESProvider
from protean.infra import registry
from tests.docs.support import domain_from_config, load_example

pytestmark = pytest.mark.no_test_domain


def test_aggregate_is_stored_through_the_named_database():
    example = load_example("guides/compose-a-domain/production-configuration/001.py")
    example.domain.init(traverse=False)

    assert example.ProductSearch.meta_.provider == "analytics"

    with example.domain.domain_context():
        repo = example.domain.repository_for(example.ProductSearch)
        assert repo._provider is example.domain.providers["analytics"]

        product = example.ProductSearch()
        repo.add(product)
        assert repo.get(product.id).id == product.id


ELASTICSEARCH = "guides/compose-a-domain/production-configuration/elasticsearch.toml"
MULTIPLE = "guides/compose-a-domain/production-configuration/multiple_databases.toml"


def _base_urls(domain, name):
    """Build the provider ``name`` without ``domain.init()`` and return its node base URLs.

    ``domain.init()`` would ping the documented hosts, which are not the test service.
    """
    conn_info = dict(domain.config["databases"][name])
    provider = registry.providers.get(conn_info["provider"])(name, domain, conn_info)
    assert type(provider) is ESProvider
    return [node.base_url for node in provider._client.transport.node_pool.all()]


@pytest.mark.elasticsearch
def test_elasticsearch_bare_host_gets_the_default_port(tmp_path):
    domain = domain_from_config(ELASTICSEARCH, tmp_path)

    assert _base_urls(domain, "default") == ["http://localhost:9200"]


@pytest.mark.elasticsearch
def test_analytics_database_defaults_to_localhost(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://postgres:postgres@db:5432/app")
    monkeypatch.delenv("ES_HOST", raising=False)
    domain = domain_from_config(MULTIPLE, tmp_path)

    assert _base_urls(domain, "analytics") == ["http://localhost:9200"]


@pytest.mark.elasticsearch
def test_analytics_database_reads_es_host(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://postgres:postgres@db:5432/app")
    monkeypatch.setenv("ES_HOST", "http://es:9200")
    domain = domain_from_config(MULTIPLE, tmp_path)

    assert _base_urls(domain, "analytics") == ["http://es:9200"]


def test_default_database_reads_database_url(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://postgres:postgres@db:5432/app")
    domain = domain_from_config(MULTIPLE, tmp_path)

    assert domain.config["databases"]["default"] == {
        "provider": "postgresql",
        "database_uri": "postgresql://postgres:postgres@db:5432/app",
    }
