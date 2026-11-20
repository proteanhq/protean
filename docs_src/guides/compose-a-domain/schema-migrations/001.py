# --8<-- [start:full]
from protean import Domain
from protean.fields import Integer, String

domain = Domain(name="Shop")
domain.config["databases"]["default"] = {
    "provider": "sqlite",
    "database_uri": "sqlite:///:memory:",
}


@domain.aggregate
class Product:
    name = String(max_length=50)
    price = Integer()


domain.init(traverse=False)

with domain.domain_context():
    metadata = domain.databases["default"].metadata
    tables = {
        table.name: sorted(column.name for column in table.columns)
        for table in metadata.sorted_tables
    }

print(tables)  # {'product': ['_version', 'id', 'name', 'price']}
# --8<-- [end:full]
