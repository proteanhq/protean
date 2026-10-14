# --8<-- [start:flagged]
from protean import Domain, Index
from protean.fields import Text

domain = Domain(name="app")


@domain.aggregate(indexes=[Index("body")])
class Note:
    body = Text()  # unbounded; indexed -> UNBOUNDED_INDEXED_STRING


# --8<-- [end:flagged]
