"""Run the example on ``docs/reference/adapters/database/elasticsearch.md``."""

import pytest

from tests.docs.support import load_example
from tests.shared import ELASTICSEARCH_URI

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
