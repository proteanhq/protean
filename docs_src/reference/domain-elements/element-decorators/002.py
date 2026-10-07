from protean import Domain

domain = Domain(name="Ordering")


# --8<-- [start:suppress_checks]
@domain.aggregate(suppress_checks=("AGGREGATE_NO_INVARIANTS",))
class Order: ...


# --8<-- [end:suppress_checks]
