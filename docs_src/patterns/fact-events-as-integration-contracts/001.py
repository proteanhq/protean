from protean import Domain
from protean.fields import Auto, Identifier, String

# --8<-- [start:granular_events]
customers = Domain(name="Customers")


@customers.aggregate
class Customer:
    customer_id: Auto(identifier=True)


@customers.event(part_of=Customer)
class CustomerAddressChanged:
    customer_id: Identifier(required=True)
    new_street: String(required=True)
    new_city: String(required=True)
    new_zip: String(required=True)


@customers.event(part_of=Customer)
class CustomerPhoneUpdated:
    customer_id: Identifier(required=True)
    new_phone: String(required=True)


@customers.event(part_of=Customer)
class CustomerNameCorrected:
    customer_id: Identifier(required=True)
    new_first_name: String(required=True)
    new_last_name: String(required=True)


@customers.event(part_of=Customer)
class CustomerEmailVerified:
    customer_id: Identifier(required=True)
    verified_email: String(required=True)


@customers.event(part_of=Customer)
class CustomerTierUpgraded:
    customer_id: Identifier(required=True)
    new_tier: String(required=True)


# --8<-- [end:granular_events]
