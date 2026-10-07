from protean import Domain
from protean.fields import String, ValueObject

domain = Domain(name="Identity")


@domain.value_object
class Email:
    address: String(max_length=254, required=True)


# --8<-- [start:aggregate]
@domain.aggregate
class User:
    email = ValueObject("Email")
    name: String(max_length=30)
    timezone: String(max_length=30)


# --8<-- [end:aggregate]
