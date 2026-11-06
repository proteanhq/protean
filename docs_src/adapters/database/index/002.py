# --8<-- [start:full]
from protean import Domain
from protean.fields import String

domain = Domain(name="Tables")
domain.config["databases"]["default"] = {
    "provider": "sqlite",
    "database_uri": "sqlite:///:memory:",
}


@domain.aggregate
class Customer:
    name: String(max_length=50, required=True)


domain.init(traverse=False)

with domain.domain_context():
    provider = domain.providers["default"]
    for table in provider.metadata.sorted_tables:
        print(table.schema, table.name)  # None customer
# --8<-- [end:full]
