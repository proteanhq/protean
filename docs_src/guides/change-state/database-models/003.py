import os

from protean import Domain
from protean.core.database_model import BaseDatabaseModel
from protean.fields import String, Text

domain = Domain(name="Publishing")
domain.config["databases"]["default"] = {
    "provider": "elasticsearch",
    "database_uri": {
        "hosts": [os.environ.get("ELASTICSEARCH_HOST", "http://localhost:9200")]
    },
}


# --8<-- [start:partial]
from elasticsearch.dsl import Text as ESText


@domain.aggregate
class Article:
    title = String(required=True)
    body = Text()
    category = String()


class ArticleSearchModel(BaseDatabaseModel):
    body = ESText(analyzer="english")  # Override only this field
    # title and category use the default mapping


domain.register(ArticleSearchModel, part_of=Article)
# --8<-- [end:partial]
