from protean import Domain, Index
from protean.fields import Text

domain = Domain(name="app")


# --8<-- [start:suppressed]
@domain.aggregate(
    indexes=[Index("body")],
    suppress_checks=["UNBOUNDED_INDEXED_STRING"],
)
class Note:
    body = Text()


# --8<-- [end:suppressed]
