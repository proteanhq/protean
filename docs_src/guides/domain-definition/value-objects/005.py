from protean import Domain
from protean.fields import Decimal, String

domain = Domain(name="Banking")


@domain.value_object
class Balance:
    currency: String(max_length=3, required=True)
    amount: Decimal(precision=19, scale=4, required=True)


# --8<-- [start:replace]
from decimal import Decimal as D

balance = Balance(currency="USD", amount=D("100.00"))
updated = balance.replace(amount=D("200.00"))

assert updated.amount == D("200.00")
assert updated.currency == "USD"  # unchanged fields are preserved
assert balance.amount == D("100.00")  # original is not modified
# --8<-- [end:replace]
