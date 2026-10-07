from protean import Domain
from protean.fields import Decimal, String, ValueObject

domain = Domain(name="Banking")


@domain.value_object
class Balance:
    currency: String(max_length=3, required=True)
    amount: Decimal(precision=19, scale=4, required=True, min_value=0)


@domain.aggregate
class Account:
    balance = ValueObject(Balance)
    name: String(max_length=30)


domain.init(traverse=False)


# --8<-- [start:dict]
from decimal import Decimal as D

with domain.domain_context():
    account = Account(
        balance={"currency": "USD", "amount": D("100.00")},
        name="Checking",
    )
    # Protean converts the dict to a Balance value object
    assert account.balance == Balance(currency="USD", amount=D("100.00"))
# --8<-- [end:dict]
