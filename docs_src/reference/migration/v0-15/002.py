from protean import Domain
from protean.fields import String

domain = Domain(name="Addresses")


# --8<-- [start:address]
@domain.value_object
class Address:
    street = String()
    city = String()


address = Address(street="123 Main", city="NYC")
# --8<-- [end:address]
