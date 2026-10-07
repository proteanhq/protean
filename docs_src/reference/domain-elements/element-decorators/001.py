from protean import Domain
from protean.fields import String

domain = Domain(name="Identity")


# --8<-- [start:options]
@domain.aggregate(schema_name="users", fact_events=True)
class User:
    name = String(required=True)


# --8<-- [end:options]
