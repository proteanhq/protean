from protean import Domain

domain = Domain(name="Publishing")


# --8<-- [start:auto_now]
from protean.fields import DateTime, String


@domain.aggregate
class Article:
    title: String(max_length=100)
    created_at: DateTime(auto_now_add=True)
    updated_at: DateTime(auto_now=True)


# --8<-- [end:auto_now]
