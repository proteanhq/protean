"""The example on the Choosing Adapters guide behaves as the page says."""

import pytest

from protean.adapters.repository.elasticsearch import ESProvider
from protean.adapters.repository.sqlalchemy import PostgresqlProvider
from protean.exceptions import ConfigurationError
from protean.infra import registry
from protean.utils.reflection import id_field
from tests.docs.support import domain_from_config, load_example

pytestmark = pytest.mark.no_test_domain


def test_projection_is_routed_to_the_named_search_database():
    example = load_example("guides/compose-a-domain/choosing-adapters/001.py")
    example.domain.init(traverse=False)

    assert example.ProductSearchIndex.meta_.provider == "search"
    assert id_field(example.ProductSearchIndex).field_name == "product_id"
    assert example.domain.registry.elements == {
        "projections": [example.ProductSearchIndex]
    }


PRODUCTION = "guides/compose-a-domain/choosing-adapters/production.toml"


@pytest.mark.elasticsearch
def test_search_database_connects_to_the_es_host(tmp_path, monkeypatch):
    # Built without domain.init(), which would ping the host.
    monkeypatch.setenv("DATABASE_URL", "postgresql://postgres:postgres@db:5432/app")
    monkeypatch.setenv("ES_HOST", "http://es:9200")
    domain = domain_from_config(PRODUCTION, tmp_path)
    conn_info = dict(domain.config["databases"]["search"])

    provider = registry.providers.get(conn_info["provider"])(
        "search", domain, conn_info
    )

    assert type(provider) is ESProvider
    nodes = provider._client.transport.node_pool.all()
    assert [node.base_url for node in nodes] == ["http://es:9200"]


def test_default_database_reads_database_url(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://postgres:postgres@db:5432/app")
    monkeypatch.setenv("ES_HOST", "http://es:9200")
    domain = domain_from_config(PRODUCTION, tmp_path)

    default = domain.config["databases"]["default"]
    assert registry.providers.get(default["provider"]) is PostgresqlProvider
    assert default["database_uri"] == "postgresql://postgres:postgres@db:5432/app"


def test_loading_without_es_host_names_the_variable(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://postgres:postgres@db:5432/app")
    monkeypatch.delenv("ES_HOST", raising=False)

    with pytest.raises(ConfigurationError, match="ES_HOST"):
        domain_from_config(PRODUCTION, tmp_path)
