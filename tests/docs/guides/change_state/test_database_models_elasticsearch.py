"""Check the Elasticsearch examples on docs/guides/change-state/database-models.md.

Each example points its domain at Elasticsearch, so these tests need the
service and run in the FULL leg. Every test builds the example's indexes under
a prefix (a model's own ``schema_name`` is used as given) and drops them
afterwards.
"""

import pytest

from tests.docs.support import load_example
from tests.shared import ELASTICSEARCH_URI

pytestmark = [pytest.mark.no_test_domain, pytest.mark.elasticsearch]


@pytest.fixture(autouse=True)
def elasticsearch_host(monkeypatch):
    monkeypatch.setenv("ELASTICSEARCH_HOST", ELASTICSEARCH_URI["hosts"][0])


def init(module):
    module.domain.config["databases"]["default"]["NAMESPACE_PREFIX"] = "docs-models"
    module.domain.init(traverse=False)
    return module


def index_mapping(module, aggregate_cls):
    """Create the indexes, return the aggregate's index name and fields, drop them."""
    with module.domain.domain_context():
        index = module.domain.repository_for(aggregate_cls)._database_model._index
        provider = module.domain.providers["default"]
        provider._create_database_artifacts()
        try:
            mapping = provider.get_connection().indices.get_mapping(index=index._name)
        finally:
            provider._drop_database_artifacts()
    return index._name, mapping[index._name]["mappings"]["properties"]


def test_field_types_reach_the_index_mapping():
    example = init(load_example("guides/change-state/database-models/002.py"))

    _, properties = index_mapping(example, example.Product)

    assert properties["name"] == {"type": "keyword"}
    assert properties["description"] == {"type": "text", "analyzer": "standard"}


def test_partial_model_keeps_the_default_mapping_for_other_fields():
    example = init(load_example("guides/change-state/database-models/003.py"))

    _, properties = index_mapping(example, example.Article)

    assert properties["body"] == {"type": "text", "analyzer": "english"}
    # Fields the model leaves out keep Protean's default mapping
    assert properties["title"] == {"type": "keyword"}
    assert properties["category"] == {"type": "keyword"}


def test_an_elasticsearch_provider_uses_the_elasticsearch_model():
    example = init(load_example("guides/change-state/database-models/004.py"))

    with example.domain.domain_context():
        model = example.domain.repository_for(example.Customer)._database_model

    assert issubclass(model, example.CustomerSearchModel)
    assert not issubclass(model, example.CustomerWriteModel)

    index_name, properties = index_mapping(example, example.Customer)

    assert index_name == "customer_index"
    assert properties["name"] == {"type": "keyword"}
