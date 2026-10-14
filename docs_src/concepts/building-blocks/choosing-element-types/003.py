from protean import Domain

domain = Domain(name="ChoosingElementsTooManyAggregates")


# --8<-- [start:too_many_aggregates]
# ❌ Bad: Making every entity an aggregate
@domain.aggregate
class User: ...


@domain.aggregate
class Address: ...  # Should be Value Object


@domain.aggregate
class Phone: ...  # Should be Value Object


# --8<-- [end:too_many_aggregates]
