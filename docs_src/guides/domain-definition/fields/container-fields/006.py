from protean import Domain

domain = Domain(name="Customers")


# --8<-- [start:dict_of_value_objects]
from protean.fields import Dict, String, ValueObject


@domain.value_object
class Address:
    street: String(max_length=100)
    city: String(max_length=25)


@domain.aggregate
class Customer:
    name: String(max_length=50)
    addresses: Dict(value_type=ValueObject(Address))  # {"home": Address(...), ...}


# --8<-- [end:dict_of_value_objects]
