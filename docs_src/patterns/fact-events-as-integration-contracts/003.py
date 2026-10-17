# --8<-- [start:subscriber]
from protean import Domain
from protean.exceptions import ObjectNotFoundError
from protean.fields import Auto, Identifier, String

fulfillment = Domain(name="Fulfillment")


@fulfillment.aggregate
class ShippingProfile:
    """Fulfillment domain's local model of a customer."""

    profile_id: Auto(identifier=True)
    customer_id: Identifier(required=True)
    full_name: String()
    email: String()
    phone: String()
    street: String()
    city: String()
    zip_code: String()
    tier: String(default="STANDARD")


@fulfillment.subscriber(stream="customer_fact_events")
class CustomerFactEventSubscriber:
    def __call__(self, payload: dict) -> None:
        # Protean publishes the event fields under "data", beside "metadata"
        data = payload["data"]
        repo = fulfillment.repository_for(ShippingProfile)

        try:
            profile = repo.find_by(customer_id=data["customer_id"])
        except ObjectNotFoundError:
            profile = ShippingProfile(customer_id=data["customer_id"])

        # Overwrite everything from the latest snapshot
        address = data.get("shipping_address") or {}
        profile.full_name = f"{data['first_name']} {data['last_name']}"
        profile.email = data["email"]
        profile.phone = data.get("phone") or ""
        profile.street = address.get("street", "")
        profile.city = address.get("city", "")
        profile.zip_code = address.get("zip_code", "")
        profile.tier = data.get("tier", "STANDARD")

        repo.add(profile)


# --8<-- [end:subscriber]

fulfillment.config["message_processing"] = "sync"
