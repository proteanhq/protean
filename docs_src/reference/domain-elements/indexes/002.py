from protean import Domain, Index
from protean.fields import Dict

domain = Domain(name="Ordering")


# --8<-- [start:from_sql]
@domain.aggregate(
    indexes=[
        Index.from_sql(
            "postgresql",
            'CREATE INDEX ix_order_data_gin ON "order" USING gin (data jsonb_path_ops)',
        ),
    ]
)
class Order:
    data: Dict()


# --8<-- [end:from_sql]
