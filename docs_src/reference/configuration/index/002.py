from protean import Domain
from protean.fields import String

domain = Domain(name="Users", config={})


# --8<-- [start:aggregate]
@domain.aggregate(provider="sqlite")  # (1)
class User:
    name: String(max_length=50)
    email: String(max_length=254)


# --8<-- [end:aggregate]
