# --8<-- [start:current]
from protean import Domain
from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.core.upcaster import BaseUpcaster
from protean.core.value_object import BaseValueObject
from protean.fields import Identifier, String, ValueObject

domain = Domain(name="Customers")


@domain.value_object
class Address(BaseValueObject):
    street = String()
    city = String()
    state = String()
    zip_code = String()


@domain.aggregate
class Customer(BaseAggregate):
    customer_id = Identifier(identifier=True)


@domain.event(part_of=Customer)
class CustomerRegistered(BaseEvent):
    __version__ = 3
    customer_id = Identifier(required=True)
    first_name = String(required=True)
    last_name = String()
    address = ValueObject(Address)


# --8<-- [end:current]


# --8<-- [start:split-name]
@domain.upcaster(event_type=CustomerRegistered, from_version=1, to_version=2)
class UpcastCustomerRegisteredV1ToV2(BaseUpcaster):
    def upcast(self, data: dict) -> dict:
        full_name = data.pop("customer_name", "")
        parts = full_name.split(" ", 1)
        data["first_name"] = parts[0]
        data["last_name"] = parts[1] if len(parts) > 1 else ""
        return data


# --8<-- [end:split-name]


# --8<-- [start:nest-address]
@domain.upcaster(event_type=CustomerRegistered, from_version=2, to_version=3)
class UpcastCustomerRegisteredV2ToV3(BaseUpcaster):
    def upcast(self, data: dict) -> dict:
        data["address"] = {
            "street": data.pop("street", ""),
            "city": data.pop("city", ""),
            "state": data.pop("state", ""),
            "zip_code": data.pop("zip_code", ""),
        }
        return data


# --8<-- [end:nest-address]
