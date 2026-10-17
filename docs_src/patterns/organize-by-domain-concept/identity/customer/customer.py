# --8<-- [start:customer]
from identity import domain

from protean.fields import HasMany, Identifier, String


@domain.entity(part_of="Customer")
class Address:
    street = String(required=True)
    city = String(required=True)


@domain.aggregate
class Customer:
    name = String(required=True)
    addresses = HasMany(Address)
    default_address_id = Identifier()

    def add_address(self, street, city):
        self.add_addresses(Address(street=street, city=city))

    def remove_address(self, address_id):
        address = self.get_one_from_addresses(id=address_id)
        self.remove_addresses(address)
        if self.default_address_id == address_id:
            self.default_address_id = None

    def set_default_address(self, address_id):
        self.get_one_from_addresses(id=address_id)
        self.default_address_id = address_id


# --8<-- [end:customer]
