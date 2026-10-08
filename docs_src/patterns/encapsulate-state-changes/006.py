# --8<-- [start:update_shipping_address]
from protean import Domain
from protean.exceptions import ValidationError
from protean.fields import Auto, String, ValueObject

domain = Domain(name="EncapsulateStateChangesAddresses")


@domain.value_object
class ShippingAddress:
    street: String(required=True)
    city: String(required=True)
    state: String(required=True)
    postal_code: String(required=True)
    country: String(required=True)


@domain.aggregate
class Order:
    order_id: Auto(identifier=True)
    status: String(default="draft")
    shipping_address = ValueObject(ShippingAddress)

    def update_shipping_address(self, new_address: ShippingAddress) -> None:
        if self.status != "draft":
            raise ValidationError(
                {"status": ["Cannot change address after order is placed"]}
            )
        self.shipping_address = new_address


# --8<-- [end:update_shipping_address]
