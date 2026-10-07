from protean import Domain
from protean.fields import Auto, String

domain = Domain(name="Metering")


# --8<-- [start:aggregate]
@domain.aggregate
class Reading:
    reading_id: Auto(identifier=True, identity_type="integer")
    value: String(max_length=50)


# --8<-- [end:aggregate]
