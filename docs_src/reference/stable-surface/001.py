from protean import Domain
from protean.fields import DateTime

domain = Domain(name="Ordering")


# --8<-- [start:annotation_style]
@domain.aggregate
class Order:
    placed_at: DateTime(required=True)


# --8<-- [end:annotation_style]
