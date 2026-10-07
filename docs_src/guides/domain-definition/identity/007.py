from protean import Domain
from protean.fields import Auto, String

domain = Domain(name="Auditing")


# --8<-- [start:aggregate]
@domain.aggregate
class AuditEntry:
    entry_id: Auto(identifier=True, increment=True, identity_type="integer")
    message: String(max_length=500, required=True)


# --8<-- [end:aggregate]
