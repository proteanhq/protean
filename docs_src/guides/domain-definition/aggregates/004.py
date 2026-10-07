from protean import Domain

domain = Domain(name="Catalogue")


# --8<-- [start:aggregates]
@domain.aggregate(limit=500)
class Product: ...


@domain.aggregate(limit=None)  # No limit
class AuditLog: ...


# --8<-- [end:aggregates]
