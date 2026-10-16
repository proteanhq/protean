from protean import Domain, handle
from protean.fields import HasMany, Identifier, String
from protean.utils.globals import current_domain

domain = Domain(name="Identity")
domain.config["command_processing"] = "sync"


# --8<-- [start:customer]
# customer/customer.py


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


# --8<-- [start:addresses]
# customer/addresses.py


@domain.command(part_of="Customer")
class AddAddress:
    customer_id = Identifier(required=True)
    street = String(required=True)
    city = String(required=True)


@domain.command(part_of="Customer")
class RemoveAddress:
    customer_id = Identifier(required=True)
    address_id = Identifier(required=True)


@domain.command(part_of="Customer")
class SetDefaultAddress:
    customer_id = Identifier(required=True)
    address_id = Identifier(required=True)


@domain.command_handler(part_of="Customer")
class ManageAddressesHandler:
    @handle(AddAddress)
    def add_address(self, command):
        repo = current_domain.repository_for(Customer)
        customer = repo.get(command.customer_id)
        customer.add_address(command.street, command.city)
        repo.add(customer)

    @handle(RemoveAddress)
    def remove_address(self, command):
        repo = current_domain.repository_for(Customer)
        customer = repo.get(command.customer_id)
        customer.remove_address(command.address_id)
        repo.add(customer)

    @handle(SetDefaultAddress)
    def set_default_address(self, command):
        repo = current_domain.repository_for(Customer)
        customer = repo.get(command.customer_id)
        customer.set_default_address(command.address_id)
        repo.add(customer)


# --8<-- [end:addresses]
