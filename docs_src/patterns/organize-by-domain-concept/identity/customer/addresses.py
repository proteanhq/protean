# --8<-- [start:addresses]
from identity import domain
from identity.customer.customer import Customer

from protean import handle
from protean.fields import Identifier, String
from protean.utils.globals import current_domain


@domain.command(part_of=Customer)
class AddAddress:
    customer_id = Identifier(required=True)
    street = String(required=True)
    city = String(required=True)


@domain.command(part_of=Customer)
class RemoveAddress:
    customer_id = Identifier(required=True)
    address_id = Identifier(required=True)


@domain.command(part_of=Customer)
class SetDefaultAddress:
    customer_id = Identifier(required=True)
    address_id = Identifier(required=True)


@domain.command_handler(part_of=Customer)
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
