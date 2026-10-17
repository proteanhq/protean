import httpx

from protean import Domain, current_domain, handle
from protean.fields import Identifier, String

domain = Domain(name="Customers")
domain.config["event_processing"] = "sync"


# --8<-- [start:customer]
VALIDATOR_URL = "https://address-validator.example.com/normalize"


@domain.event(part_of="Customer")
class AddressSubmitted:
    customer_id: Identifier(required=True)
    raw_address: String(required=True)


@domain.aggregate
class Customer:
    customer_id: Identifier(identifier=True)
    address: String()

    def submit_address(self, raw_address):
        self.raise_(
            AddressSubmitted(customer_id=self.customer_id, raw_address=raw_address)
        )

    def set_address(self, normalized):
        self.address = normalized


# --8<-- [end:customer]


# --8<-- [start:normalize]
@domain.event_handler(part_of=Customer)
class CustomerAddressHandler:
    @handle(AddressSubmitted)
    def normalize_and_store(self, event):
        # The call comes first, so the transaction opens at repo.get, after it returns.
        result = httpx.post(VALIDATOR_URL, json={"address": event.raw_address}).json()

        repo = current_domain.repository_for(Customer)
        customer = repo.get(event.customer_id)
        customer.set_address(result["normalized"])
        repo.add(customer)


# --8<-- [end:normalize]
