# --8<-- [start:aggregate]
from protean import Domain
from protean.fields import Float, String, ValueObject

domain = Domain(name="Banking")


@domain.value_object
class Money:
    currency: String(max_length=3, required=True)
    amount: Float(min_value=0, required=True)


@domain.aggregate
class Account:
    owner: String(max_length=100, required=True)
    balance = ValueObject(Money)


# --8<-- [end:aggregate]
