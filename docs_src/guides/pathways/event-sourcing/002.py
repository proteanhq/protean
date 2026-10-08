# --8<-- [start:mixing]
from protean import Domain

domain = Domain(name="Shop")


@domain.aggregate  # Standard CQRS: state stored as snapshots
class Product: ...


@domain.aggregate(event_sourced=True)  # Event Sourced: state from events
class Order: ...


# --8<-- [end:mixing]
