# --8<-- [start:full]
from bookshelf.models import Money


def test_money_equality():
    m1 = Money(amount=12.99, currency="USD")
    m2 = Money(amount=12.99, currency="USD")
    m3 = Money(amount=14.99, currency="USD")

    assert m1 == m2
    assert m1 != m3


# --8<-- [end:full]
