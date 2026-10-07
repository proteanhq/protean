# --8<-- [start:full]
import os

from elasticsearch import dsl

from protean import Domain
from protean.fields import String

domain = Domain(name="Articles")
domain.config["databases"]["default"] = {
    "provider": "elasticsearch",
    "database_uri": {
        "hosts": [os.environ.get("ELASTICSEARCH_HOST", "http://localhost:9200")]
    },
}


@domain.aggregate(schema_name="articles")
class Article:
    title: String()
    body: String()
    category: String()


@domain.database_model(part_of=Article)
class ArticleModel:
    # Full-text search with .keyword subfield for exact match
    title = dsl.Text(analyzer="standard", fields={"keyword": dsl.Keyword()})
    # Full-text search only
    body = dsl.Text(analyzer="english")
    # category is not listed: auto-mapped as Keyword from the aggregate


domain.init(traverse=False)
# --8<-- [end:full]
