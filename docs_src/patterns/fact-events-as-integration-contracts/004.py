from protean import Domain
from protean.exceptions import ObjectNotFoundError
from protean.fields import Boolean, Identifier, String

fulfillment = Domain(name="Fulfillment")


# --8<-- [start:consumers]
# ── Fulfillment Domain ──────────────────────────────────────────


@fulfillment.subscriber(stream="customer_fact_events")
class CustomerFactEventSubscriber:
    def __call__(self, payload: dict) -> None:
        # Extracts name, address, tier for shipping decisions
        ...


# ── Analytics Domain ────────────────────────────────────────────

analytics = Domain(name="Analytics")


@analytics.aggregate
class CustomerMetrics:
    customer_id: Identifier(required=True)
    tier: String()
    email_domain: String()
    has_phone: Boolean(default=False)
    has_address: Boolean(default=False)


@analytics.subscriber(stream="customer_fact_events")
class CustomerAnalyticsSubscriber:
    def __call__(self, payload: dict) -> None:
        data = payload["data"]
        repo = analytics.repository_for(CustomerMetrics)

        try:
            metrics = repo.find_by(customer_id=data["customer_id"])
        except ObjectNotFoundError:
            metrics = CustomerMetrics(customer_id=data["customer_id"])

        # Extracts only the fields Analytics cares about
        metrics.tier = data.get("tier", "STANDARD")
        metrics.email_domain = data["email"].split("@")[-1]
        metrics.has_phone = bool(data.get("phone"))
        metrics.has_address = bool(data.get("shipping_address"))

        repo.add(metrics)


# --8<-- [end:consumers]

analytics.config["message_processing"] = "sync"
