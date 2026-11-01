from protean import Domain
from protean.fields import String

domain = Domain()


@domain.aggregate
class Order:
    description: String(max_length=100)
    created_by: String(max_length=50)
    updated_by: String(max_length=50)


# --8<-- [start:stamp_audit]
from protean.utils.globals import g


@domain.aggregate_enricher
def stamp_audit(aggregate):
    if not hasattr(aggregate, "updated_by"):  # an aggregate without audit fields
        return
    user = g.get("current_user")
    aggregate.updated_by = user
    if aggregate.created_by is None:  # set once, on create
        aggregate.created_by = user


# --8<-- [end:stamp_audit]


# --8<-- [start:save_as]
def save_as_alice(order):
    with domain.domain_context(current_user="alice"):
        domain.repository_for(Order).add(order)


# --8<-- [end:save_as]
