from protean import Domain
from protean.fields import Integer, String

domain = Domain()


# --8<-- [start:limit]
@domain.aggregate(limit=50)
class Person:
    # Queries will return at most 50 records by default
    id: Integer(identifier=True)
    name: String(required=True, max_length=50)


# --8<-- [end:limit]
