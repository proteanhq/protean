from protean import Domain
from protean.fields import String

domain = Domain(name="CreatingIdentitiesEarlyBooks")


# --8<-- [start:natural-key]
@domain.aggregate
class Book:
    isbn: String(max_length=13, identifier=True)
    title: String(max_length=200, required=True)


# --8<-- [end:natural-key]
