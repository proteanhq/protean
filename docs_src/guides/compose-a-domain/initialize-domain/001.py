from protean import Domain
from protean.fields import String

domain = Domain()


@domain.aggregate
class User:
    name: String(max_length=50)


# --8<-- [start:init]
domain.init()
# --8<-- [end:init]
