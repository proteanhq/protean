from decimal import Decimal as D

from protean import Domain
from protean.fields import Decimal, String

domain = Domain(name="Pricing")


@domain.value_object
class Balance:
    currency: String(max_length=3, required=True)
    amount: Decimal(precision=19, scale=4, required=True)


@domain.value_object
class Email:
    address: String(max_length=254, required=True)


# --8<-- [start:hash]
prices = {
    Balance(currency="USD", amount=D("9.99")): "budget",
    Balance(currency="USD", amount=D("99.99")): "premium",
}

unique_emails = {Email(address="a@b.com"), Email(address="c@d.com")}
# --8<-- [end:hash]
