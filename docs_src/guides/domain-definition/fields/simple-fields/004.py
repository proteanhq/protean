# --8<-- [start:full]
from protean import Domain
from protean.fields import Float, String

domain = Domain()


@domain.aggregate
class Account:
    name: String(max_length=255)
    balance: Float(default=0.0)


# --8<-- [end:full]
