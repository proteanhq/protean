"""Run the example on ``docs/reference/adapters/database/index.md``."""

import pytest

from protean.adapters.repository.elasticsearch import ESProvider
from protean.adapters.repository.memory import MemoryProvider
from protean.adapters.repository.sqlalchemy import PostgresqlProvider, SAProvider
from protean.infra import registry
from tests.docs.support import domain_from_config, load_example
from tests.shared import ELASTICSEARCH_PORT, POSTGRES_PORT, POSTGRES_URI

pytestmark = pytest.mark.no_test_domain


def test_raw_query_returns_only_matching_rows():
    example = load_example("adapters/database/index/001.py")

    # Tim is 17, so the "age__gt": 21 filter leaves only Ada
    assert [(row["name"], row["age"]) for row in example.results] == [("Ada", 36)]


@pytest.mark.sqlite
def test_metadata_lists_the_aggregate_table():
    example = load_example("adapters/database/index/002.py")

    provider = example.domain.providers["default"]
    assert isinstance(provider, SAProvider)
    with example.domain.domain_context():
        assert [table.name for table in provider.metadata.sorted_tables] == ["customer"]


MULTIPLE = "adapters/database/index/multiple_databases.toml"


@pytest.mark.elasticsearch
@pytest.mark.postgresql
def test_configuration_shown_builds_three_providers(tmp_path, monkeypatch):
    es_host = f"http://localhost:{ELASTICSEARCH_PORT}"
    monkeypatch.setenv("ELASTICSEARCH_HOST", es_host)
    monkeypatch.setenv("DATABASE_URL", POSTGRES_URI)
    domain = domain_from_config(MULTIPLE, tmp_path)
    domain.init(traverse=False)

    providers = domain.providers
    assert type(providers["default"]) is MemoryProvider
    assert type(providers["analytics"]) is ESProvider
    assert type(providers["reporting"]) is PostgresqlProvider
    nodes = providers["analytics"]._client.transport.node_pool.all()
    assert [node.base_url for node in nodes] == [es_host]
    url = providers["reporting"]._engine.url
    assert (url.host, url.port, url.database) == (
        "localhost",
        POSTGRES_PORT,
        "postgres",
    )


def test_configuration_shown_defaults_to_the_documented_values(tmp_path, monkeypatch):
    monkeypatch.delenv("ELASTICSEARCH_HOST", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    domain = domain_from_config(MULTIPLE, tmp_path)

    databases = domain.config["databases"]
    assert databases["analytics"]["database_uri"] == {
        "hosts": ["http://localhost:9200"]
    }
    assert (
        databases["reporting"]["database_uri"]
        == "postgresql://postgres:postgres@localhost:5432/reports"
    )


@pytest.mark.elasticsearch
def test_elasticsearch_client_gets_the_documented_host(tmp_path, monkeypatch):
    # Built without domain.init(), which would ping localhost:9200.
    monkeypatch.delenv("ELASTICSEARCH_HOST", raising=False)
    domain = domain_from_config(MULTIPLE, tmp_path)
    conn_info = dict(domain.config["databases"]["analytics"])

    provider = registry.providers.get("elasticsearch")("analytics", domain, conn_info)

    nodes = provider._client.transport.node_pool.all()
    assert [node.base_url for node in nodes] == ["http://localhost:9200"]
