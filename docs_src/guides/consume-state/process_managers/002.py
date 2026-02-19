from protean import Domain, handle
from protean.fields import Float, Identifier, String

domain = Domain(__file__, "billing")


@domain.event(part_of="Invoice")
class ExternalPaymentReceived:
    ext_order_ref: Identifier(required=True)
    amount: Float(required=True)


@domain.aggregate
class Invoice:
    ext_order_ref: Identifier(required=True)
    amount: Float(required=True)


@domain.process_manager(stream_categories=["billing::invoice"])
class PaymentReconciliationPM:
    order_id: Identifier()
    status: String(default="pending")

    @handle(
        ExternalPaymentReceived,
        start=True,
        correlate={"order_id": "ext_order_ref"},  # (1)
    )
    def on_payment_received(self, event: ExternalPaymentReceived) -> None:
        self.order_id = event.ext_order_ref
        self.status = "received"
        self.mark_as_complete()
