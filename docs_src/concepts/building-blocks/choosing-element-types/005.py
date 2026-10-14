from protean import Domain
from protean.fields import String

domain = Domain(name="MissingAggregate")


# --8<-- [start:missing_aggregate]
# ❌ Bad: Entity without an aggregate
@domain.entity  # Missing part_of parameter
class Comment:
    content: String(max_length=500)


# Error: Entity needs to be associated with an Aggregate
# --8<-- [end:missing_aggregate]
