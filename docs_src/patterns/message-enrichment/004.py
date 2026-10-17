from protean import Domain
from protean.fields import Auto, Float, Identifier
from protean.utils.globals import g

domain = Domain(name="Billing")

ENABLED_FLAGS = {"new_pricing_model"}


def is_feature_enabled(name: str) -> bool:
    return name in ENABLED_FLAGS


# --8<-- [start:feature_flags]
@domain.event_enricher
def enrich_with_feature_flags(event, aggregate):
    """Attach active feature flags only for events that need them."""
    # Only enrich billing-related events
    if event.__class__.__name__ in ("InvoiceGenerated", "PaymentProcessed"):
        return {
            "feature_flags": {
                "new_pricing_model": is_feature_enabled("new_pricing_model"),
                "tax_v2": is_feature_enabled("tax_v2"),
            }
        }
    return {}


# --8<-- [end:feature_flags]


# --8<-- [start:tracing]
@domain.event_enricher
def enrich_with_tracing(event, aggregate):
    """Bridge domain enrichment with external distributed tracing."""
    traceparent = getattr(g, "traceparent", None)
    return {
        "trace_id": traceparent.trace_id if traceparent else None,
        "span_id": traceparent.parent_id if traceparent else None,
    }


# --8<-- [end:tracing]


@domain.aggregate
class Invoice:
    invoice_id: Auto(identifier=True)
    amount: Float(required=True)

    def generate(self):
        self.raise_(InvoiceGenerated(invoice_id=self.invoice_id, amount=self.amount))

    def remind(self):
        self.raise_(InvoiceReminderSent(invoice_id=self.invoice_id))


@domain.event(part_of=Invoice)
class InvoiceGenerated:
    invoice_id: Identifier(required=True)
    amount: Float(required=True)


@domain.event(part_of=Invoice)
class InvoiceReminderSent:
    invoice_id: Identifier(required=True)
