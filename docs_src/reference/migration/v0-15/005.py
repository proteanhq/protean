import os

from protean import Domain
from protean.fields import String

domain = Domain(name="Publishing")
domain.config["databases"]["elasticsearch"] = {
    "provider": "elasticsearch",
    "database_uri": {
        "hosts": [os.environ.get("ELASTICSEARCH_HOST", "http://localhost:9200")]
    },
}


# --8<-- [start:recreate_indexes]
def recreate_indexes():
    with domain.domain_context():
        provider = domain.providers["elasticsearch"]
        provider._drop_database_artifacts()
        provider._create_database_artifacts()


# --8<-- [end:recreate_indexes]


# --8<-- [start:article]
@domain.aggregate(provider="elasticsearch")
class Article:
    title = String(required=True)
    category = String()


# --8<-- [end:article]


# --8<-- [start:custom_model]
from elasticsearch import dsl


@domain.database_model(part_of=Article)
class ArticleModel:
    # Text field with analyzer for full-text search
    title = dsl.Text(analyzer="standard", fields={"keyword": dsl.Keyword()})
    # Fields not listed here are auto-mapped from the aggregate


# --8<-- [end:custom_model]
