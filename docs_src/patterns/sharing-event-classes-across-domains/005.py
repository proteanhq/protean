from protean import Domain

# --8<-- [start:external_event]
from protean.core.event import BaseEvent
from protean.fields import Float, Identifier

fulfillment_domain = Domain(name="Fulfillment")


# Fulfillment domain's own class, not imported from Billing
class PaymentReceived(BaseEvent):
    payment_id = Identifier(required=True)
    order_id = Identifier(required=True)
    amount = Float()


# Register with the type string the Billing domain publishes
fulfillment_domain.register_external_event(
    PaymentReceived, "Billing.PaymentReceived.v1"
)
# --8<-- [end:external_event]
