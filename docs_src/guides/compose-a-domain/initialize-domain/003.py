from protean import Domain
from protean.fields import String

domain = Domain()


# --8<-- [start:string-reference]
@domain.entity(part_of="User")
class Account:
    email: String(max_length=254)


@domain.aggregate
class User:
    name: String(max_length=50)


# --8<-- [end:string-reference]
