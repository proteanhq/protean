# --8<-- [start:full]
from protean import Domain
from protean.fields import Decimal, String

domain = Domain()


@domain.value_object
class Balance:
    currency: String(max_length=3, required=True)
    amount: Decimal(precision=19, scale=4, required=True)


# --8<-- [end:full]
