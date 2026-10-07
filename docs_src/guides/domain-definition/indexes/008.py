from protean import Domain, Index
from protean.fields import Dict

domain = Domain(name="Documents")


# --8<-- [start:aggregate]
@domain.aggregate(
    indexes=[
        Index.from_sql(
            "postgresql",
            "CREATE INDEX ix_doc_data_gin ON document USING gin (data jsonb_path_ops)",
        ),
    ]
)
class Document:
    data = Dict()


# --8<-- [end:aggregate]
