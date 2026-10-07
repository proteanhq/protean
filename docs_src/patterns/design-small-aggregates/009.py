from protean import Domain
from protean.fields import Identifier

domain = Domain(name="SmallAggregatesCorrectReference")


# --8<-- [start:correct]
# Correct: identity reference to another aggregate
@domain.aggregate
class Order:
    customer_id: Identifier(required=True)  # References Customer


# --8<-- [end:correct]
