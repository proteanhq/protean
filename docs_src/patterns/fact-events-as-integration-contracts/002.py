# --8<-- [start:customer]
from protean import Domain, handle
from protean.fields import Auto, Identifier, String, ValueObject

customers = Domain(name="Customers")


@customers.value_object
class Address:
    street: String(max_length=200)
    city: String(max_length=100)
    zip_code: String(max_length=20)
    country: String(max_length=50)


@customers.aggregate(fact_events=True)
class Customer:
    customer_id: Auto(identifier=True)
    first_name: String(required=True, max_length=50)
    last_name: String(required=True, max_length=50)
    email: String(required=True)
    phone: String()
    tier: String(default="STANDARD")
    shipping_address = ValueObject(Address)

    def correct_name(self, first_name: str, last_name: str):
        self.first_name = first_name
        self.last_name = last_name
        self.raise_(
            CustomerNameCorrected(
                customer_id=self.customer_id,
                new_first_name=first_name,
                new_last_name=last_name,
            )
        )

    def update_address(self, address: Address):
        self.shipping_address = address
        self.raise_(
            CustomerAddressChanged(
                customer_id=self.customer_id,
                new_street=address.street,
                new_city=address.city,
                new_zip=address.zip_code,
            )
        )

    def upgrade_tier(self, new_tier: str):
        self.tier = new_tier
        self.raise_(
            CustomerTierUpgraded(
                customer_id=self.customer_id,
                new_tier=new_tier,
            )
        )


# --8<-- [end:customer]

customers.config["event_processing"] = "sync"

notifications = []


def send_address_verification(**details):
    notifications.append(("address_verification", details))


def send_tier_upgrade_notification(**details):
    notifications.append(("tier_upgrade", details))


# --8<-- [start:delta_events]
@customers.event(part_of=Customer)
class CustomerNameCorrected:
    customer_id: Identifier(required=True)
    new_first_name: String(required=True)
    new_last_name: String(required=True)


@customers.event(part_of=Customer)
class CustomerAddressChanged:
    customer_id: Identifier(required=True)
    new_street: String(required=True)
    new_city: String(required=True)
    new_zip: String(required=True)


@customers.event(part_of=Customer)
class CustomerTierUpgraded:
    customer_id: Identifier(required=True)
    new_tier: String(required=True)


@customers.event_handler(part_of=Customer)
class CustomerNotificationHandler:
    @handle(CustomerAddressChanged)
    def on_address_changed(self, event: CustomerAddressChanged):
        # Send address verification email -- only triggers on address changes
        send_address_verification(
            customer_id=event.customer_id,
            new_city=event.new_city,
            new_zip=event.new_zip,
        )

    @handle(CustomerTierUpgraded)
    def on_tier_upgraded(self, event: CustomerTierUpgraded):
        # Send congratulations -- only triggers on tier changes
        send_tier_upgrade_notification(
            customer_id=event.customer_id,
            new_tier=event.new_tier,
        )


# --8<-- [end:delta_events]
