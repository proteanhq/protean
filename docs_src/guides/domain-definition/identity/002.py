# --8<-- [start:aggregate]
from protean import Domain
from protean.fields import Auto, String

domain = Domain(name="Accounts")


@domain.aggregate
class User:
    user_id: Auto(identifier=True)
    name: String(required=True)


# --8<-- [end:aggregate]
