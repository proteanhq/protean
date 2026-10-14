from protean import Domain
from protean.fields import String

domain = Domain(name="MutableValueObject")


@domain.value_object
class Address:
    street: String()
    city: String()


domain.init(traverse=False)

# --8<-- [start:mutable_value_object]
# ❌ Bad: Trying to modify value object
address = Address(street="123 Main St", city="NYC")
address.street = "456 Oak Ave"  # Will raise IncorrectUsageError
# --8<-- [end:mutable_value_object]
