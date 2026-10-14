from protean import Domain
from protean.fields import Auto, Decimal, String

domain = Domain(name="ValueObjectWithIdentity")


# --8<-- [start:value_object_with_identity]
# ❌ Bad: Adding identity to value object
@domain.value_object
class Money:
    id: Auto(identifier=True)  # Will raise IncorrectUsageError
    amount = Decimal()
    currency: String()


# --8<-- [end:value_object_with_identity]
