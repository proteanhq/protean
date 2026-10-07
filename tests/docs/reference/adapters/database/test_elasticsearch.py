"""Run the example on ``docs/reference/adapters/database/elasticsearch.md``."""

import pytest

from protean import Domain
from protean.fields import String
from tests.docs.support import DOCS_SRC, load_example
from tests.shared import ELASTICSEARCH_PORT, ELASTICSEARCH_URI

CONFIG = DOCS_SRC / "adapters/database/elasticsearch/domain.toml"

pytestmark = [pytest.mark.no_test_domain, pytest.mark.elasticsearch]


@pytest.fixture
def example(monkeypatch):
    monkeypatch.setenv("ELASTICSEARCH_HOST", ELASTICSEARCH_URI["hosts"][0])
    return load_example("adapters/database/elasticsearch/001.py")


def test_schema_name_sets_the_index_name(example):
    with example.domain.domain_context():
        model = example.domain.repository_for(example.Article)._database_model

    assert model._index._name == "articles"


def test_custom_model_fields_reach_the_index_mapping(example):
    with example.domain.domain_context():
        provider = example.domain.providers["default"]
        provider._create_database_artifacts()
        try:
            client = provider.get_connection()
            properties = client.indices.get_mapping(index="articles")["articles"][
                "mappings"
            ]["properties"]
        finally:
            provider._drop_database_artifacts()

    assert properties["title"] == {
        "type": "text",
        "analyzer": "standard",
        "fields": {"keyword": {"type": "keyword"}},
    }
    assert properties["body"] == {"type": "text", "analyzer": "english"}
    # A field the custom model leaves out keeps Protean's default mapping
    assert properties["category"] == {"type": "keyword"}


def _domain_from(config_text, tmp_path, monkeypatch):
    (tmp_path / "domain.toml").write_text(config_text)
    monkeypatch.setenv("ELASTICSEARCH_HOST", f"http://localhost:{ELASTICSEARCH_PORT}")
    monkeypatch.setenv("PROTEAN_ENV", "staging")
    domain = Domain(root_path=str(tmp_path), name="Search")

    @domain.aggregate(provider="search")
    class Person:
        name: String()

    domain.init(traverse=False)
    with domain.domain_context():
        return domain.repository_for(Person)._database_model


def test_configuration_shown_sets_the_index_name_and_settings(tmp_path, monkeypatch):
    model = _domain_from(CONFIG.read_text(), tmp_path, monkeypatch)

    assert model._index._name == "staging-person"
    assert model._index._settings == {"number_of_shards": 3}


def test_lower_case_option_names_are_ignored(tmp_path, monkeypatch):
    text = CONFIG.read_text()
    for key in ("NAMESPACE_PREFIX", "NAMESPACE_SEPARATOR", "SETTINGS"):
        text = text.replace(key, key.lower())
    model = _domain_from(text, tmp_path, monkeypatch)

    assert model._index._name == "person"
    assert model._index._settings == {}
