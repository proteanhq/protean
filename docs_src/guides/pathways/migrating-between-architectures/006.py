from protean import Domain

domain = Domain(name="Banking")


# --8<-- [start:mixing]
# This aggregate uses event sourcing (full audit trail needed)
@domain.aggregate(event_sourced=True)
class Account: ...


# This aggregate uses regular CQRS (simple CRUD is sufficient)
@domain.aggregate
class CustomerProfile: ...


# --8<-- [end:mixing]
