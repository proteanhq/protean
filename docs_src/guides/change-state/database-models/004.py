import os

from elasticsearch.dsl import Keyword

from protean import Domain
from protean.core.database_model import BaseDatabaseModel
from protean.fields import String

domain = Domain(name="Customers")
domain.config["databases"]["default"] = {
    "provider": "elasticsearch",
    "database_uri": {
        "hosts": [os.environ.get("ELASTICSEARCH_HOST", "http://localhost:9200")]
    },
}


# --8<-- [start:multi_database]
@domain.aggregate
class Customer:
    name = String(required=True)
    email = String()


class CustomerWriteModel(BaseDatabaseModel):
    pass


class CustomerSearchModel(BaseDatabaseModel):
    name = Keyword()


domain.register(
    CustomerWriteModel,
    part_of=Customer,
    database="postgresql",
    schema_name="customers",
)
domain.register(
    CustomerSearchModel,
    part_of=Customer,
    database="elasticsearch",
    schema_name="customer_index",
)
# --8<-- [end:multi_database]
