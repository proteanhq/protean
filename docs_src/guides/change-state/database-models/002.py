import os

from protean import Domain
from protean.core.database_model import BaseDatabaseModel
from protean.fields import Float, String, Text

domain = Domain(name="Catalog")
domain.config["databases"]["default"] = {
    "provider": "elasticsearch",
    "database_uri": {
        "hosts": [os.environ.get("ELASTICSEARCH_HOST", "http://localhost:9200")]
    },
}


@domain.aggregate(schema_name="catalog_products")
class Product:
    name = String(required=True)
    description = Text()
    price = Float()


# --8<-- [start:field_types]
from elasticsearch.dsl import Keyword
from elasticsearch.dsl import Text as ESText


class ProductSearchModel(BaseDatabaseModel):
    name = Keyword()  # Exact match, no analysis
    description = ESText(analyzer="standard")  # Full-text search


domain.register(
    ProductSearchModel,
    part_of=Product,
    database="elasticsearch",
)
# --8<-- [end:field_types]
