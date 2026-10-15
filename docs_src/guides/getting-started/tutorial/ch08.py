from protean import Domain
from protean.fields import String

domain = Domain()


# --8<-- [start:indexes]
from protean import Index


@domain.aggregate(
    indexes=[
        Index("isbn", unique=True),
        Index("category"),
    ]
)
class Book:
    isbn: String(max_length=20, required=True)
    title: String(max_length=255, required=True)
    category: String(max_length=64)


# --8<-- [end:indexes]
domain.init(traverse=False)
