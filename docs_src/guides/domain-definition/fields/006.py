from protean import Domain
from protean.fields import String

domain = Domain(name="Accounts")


# --8<-- [start:aggregate]
@domain.aggregate
class User:
    email: String(required=True, unique=True)
    name: String(max_length=100)


# --8<-- [end:aggregate]
