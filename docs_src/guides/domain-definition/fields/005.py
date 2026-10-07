# --8<-- [start:aggregate]
from protean import Domain
from protean.fields import Float, Integer, String

domain = Domain(name="Marketplace")


@domain.aggregate
class Listing:
    title: String(max_length=200, min_length=3)  # length bounds
    priority: Integer(min_value=1, max_value=5)  # numeric bounds
    discount: Float(min_value=0, max_value=1)
    status: String(choices=["DRAFT", "PUBLISHED", "SOLD"])  # enumerated


# --8<-- [end:aggregate]
