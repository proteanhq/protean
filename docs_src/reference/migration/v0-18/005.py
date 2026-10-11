from protean import Domain, Index
from protean.fields import Dict

domain = Domain(name="Messaging")

# --8<-- [start:from_sql]
gin_index = Index.from_sql(
    "postgresql", "CREATE INDEX ix_data_gin ON outbox USING gin (data)"
)
# --8<-- [end:from_sql]


@domain.aggregate(indexes=[gin_index])
class Outbox:
    data: Dict()
