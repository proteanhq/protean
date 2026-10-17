# --8<-- [start:shipping]
# Shipping context: a separate domain
from protean import Domain
from protean.fields import Auto, Identifier, String, ValueObject

shipping = Domain(__file__, "Shipping")


@shipping.value_object
class Address:
    street: String(max_length=200)
    city: String(max_length=100)
    zip_code: String(max_length=20)


@shipping.aggregate
class Recipient:
    """Shipping context's model of a customer."""

    recipient_id: Auto(identifier=True)
    customer_id: Identifier(required=True)  # Correlation ID
    name: String(required=True)
    delivery_address = ValueObject(Address)

    def update_address(self, address: Address) -> None:
        self.delivery_address = address


@shipping.subscriber(stream="sales_customer_events")
class CustomerEventSubscriber:
    """Consumes customer events from the Sales context's broker stream.

    Acts as an anti-corruption layer: translates Sales' customer schema
    into Shipping's Recipient model.
    """

    def __call__(self, payload: dict) -> None:
        event_type = payload.get("type", "")

        if "CustomerRegistered" in event_type:
            self._handle_registration(payload)
        elif "CustomerAddressUpdated" in event_type:
            self._handle_address_update(payload)

    def _handle_registration(self, payload: dict) -> None:
        repo = shipping.repository_for(Recipient)
        # A redelivered registration must not create a second recipient
        if repo.query.filter(customer_id=payload["customer_id"]).all().items:
            return

        # The address arrives later, with CustomerAddressUpdated
        repo.add(Recipient(customer_id=payload["customer_id"], name=payload["name"]))

    def _handle_address_update(self, payload: dict) -> None:
        repo = shipping.repository_for(Recipient)
        recipient = repo.find_by(customer_id=payload["customer_id"])
        recipient.update_address(
            Address(
                street=payload["street"],
                city=payload["city"],
                zip_code=payload["zip_code"],
            )
        )
        repo.add(recipient)


# --8<-- [end:shipping]
