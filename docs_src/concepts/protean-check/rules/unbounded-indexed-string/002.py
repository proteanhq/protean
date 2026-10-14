from protean import Domain, Index
from protean.fields import String, Text

domain = Domain(name="app")


# --8<-- [start:compliant]
@domain.aggregate(indexes=[Index("slug")])
class Article:
    slug = String(max_length=120)  # bounded; indexed -> no finding
    body = Text()  # unbounded but not indexed -> no finding


# --8<-- [end:compliant]
