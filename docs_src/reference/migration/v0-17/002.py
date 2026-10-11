from protean import Domain

domain = Domain(name="Banking")


# --8<-- [start:event_sourced]
@domain.aggregate(event_sourced=True)  # was: is_event_sourced=True
class Account: ...


# --8<-- [end:event_sourced]
