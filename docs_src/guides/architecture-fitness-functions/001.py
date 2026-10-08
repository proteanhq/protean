# --8<-- [start:full]
from protean import Domain, Index
from protean.fields import Text

domain = Domain(name="Notes")


@domain.aggregate(
    indexes=[Index("body")],
    suppress_checks=["UNBOUNDED_INDEXED_STRING"],
)
class Note:
    body = Text()


# --8<-- [end:full]
