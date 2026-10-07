# --8<-- [start:aggregate]
from protean import Domain
from protean.fields import String

domain = Domain(name="Accounts")


@domain.aggregate
class User:
    email: String(identifier=True, required=True, max_length=254)
    name: String(required=True)


# --8<-- [end:aggregate]
