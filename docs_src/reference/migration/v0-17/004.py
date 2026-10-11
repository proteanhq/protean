from protean import Domain
from protean.fields import String

domain = Domain(name="Notes")


# --8<-- [start:unsanitized]
@domain.value_object
class Note:
    body = String(max_length=64, sanitize=False)


# --8<-- [end:unsanitized]
