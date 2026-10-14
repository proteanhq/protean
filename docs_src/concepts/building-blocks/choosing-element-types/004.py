from protean import Domain
from protean.fields import String

domain = Domain(name="ChoosingElementsPrimitiveObsession")


# --8<-- [start:primitive_obsession]
# ❌ Bad: Using primitives instead of value objects
@domain.aggregate
class User:
    email: String()  # Should be ValueObject(Email)
    phone: String()  # Should be ValueObject(Phone)
    address_line1: String()  # Should be ValueObject(Address)
    address_line2: String()
    city: String()
    postal_code: String()


# --8<-- [end:primitive_obsession]
