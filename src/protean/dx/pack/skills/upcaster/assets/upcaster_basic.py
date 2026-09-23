"""
Basic event upcasters for single-step schema evolution.

This example demonstrates:
- Defining an upcaster by extending BaseUpcaster
- Registering with @domain.upcaster(event_type=..., from_version=..., to_version=...)
- Implementing upcast(self, data: dict) -> dict
- Common transformations: adding a field, renaming a field, removing a field, computing a derived field

Domain: Order lifecycle
    - OrderPlaced evolves from v1 to v3 (add currency, rename amount -> total_amount)
    - OrderConfirmed evolves from v1 to v2 (remove legacy_code, compute confirmed_by)

Usage:
    from upcaster_basic import domain, OrderPlaced, UpcastOrderPlacedV1ToV2

    domain.init(traverse=False)
    with domain.domain_context():
        upcaster = UpcastOrderPlacedV1ToV2()
        result = upcaster.upcast({"order_id": "ORD-1", "amount": 99.99})
        assert result["currency"] == "USD"
"""

from protean import Domain
from protean.core.aggregate import apply
from protean.core.upcaster import BaseUpcaster
from protean.fields import Float, Identifier, String

# Domain setup
domain = Domain()


# --- Events (current versions) ---


@domain.event(part_of="Order")
class OrderPlaced:
    """Order was placed. Current version: v3.

    Evolution history:
        v1: order_id, amount
        v2: order_id, amount, currency (added currency with default USD)
        v3: order_id, total_amount, currency (renamed amount -> total_amount)
    """

    __version__ = 3

    order_id = Identifier(required=True)
    total_amount = Float(required=True)
    currency = String(required=True)


@domain.event(part_of="Order")
class OrderConfirmed:
    """Order was confirmed. Current version: v2.

    Evolution history:
        v1: order_id, legacy_code, operator_name
        v2: order_id, confirmed_by (removed legacy_code, renamed operator_name)
    """

    __version__ = 2

    order_id = Identifier(required=True)
    confirmed_by = String(required=True)


# --- Upcasters ---


@domain.upcaster(event_type=OrderPlaced, from_version=1, to_version=2)
class UpcastOrderPlacedV1ToV2(BaseUpcaster):
    """v1 -> v2: Add currency field.

    All orders before v2 were placed in USD.
    """

    def upcast(self, data: dict) -> dict:
        data["currency"] = "USD"
        return data


@domain.upcaster(event_type=OrderPlaced, from_version=2, to_version=3)
class UpcastOrderPlacedV2ToV3(BaseUpcaster):
    """v2 -> v3: Rename 'amount' to 'total_amount'."""

    def upcast(self, data: dict) -> dict:
        data["total_amount"] = data.pop("amount")
        return data


@domain.upcaster(event_type=OrderConfirmed, from_version=1, to_version=2)
class UpcastOrderConfirmedV1ToV2(BaseUpcaster):
    """v1 -> v2: Remove legacy_code, rename operator_name -> confirmed_by."""

    def upcast(self, data: dict) -> dict:
        # Remove obsolete field
        data.pop("legacy_code", None)
        # Rename field
        data["confirmed_by"] = data.pop("operator_name")
        return data


# --- Aggregate ---


@domain.aggregate(event_sourced=True)
class Order:
    """Event-sourced order aggregate.

    Uses @apply handlers that only handle the CURRENT event schema.
    Old event versions are transformed by upcasters before reaching @apply.
    """

    order_id = Identifier(identifier=True)
    total_amount = Float(default=0.0)
    currency = String(default="USD")
    status = String(default="DRAFT")
    confirmed_by = String()

    @classmethod
    def place(cls, order_id, total_amount, currency="USD"):
        """Factory: create a new order."""
        order = cls(
            order_id=order_id,
            total_amount=total_amount,
            currency=currency,
        )
        order.raise_(
            OrderPlaced(
                order_id=order_id,
                total_amount=total_amount,
                currency=currency,
            )
        )
        return order

    def confirm(self, confirmed_by):
        """Confirm the order."""
        if self.status == "CONFIRMED":
            raise ValueError("Order is already confirmed")
        self.raise_(OrderConfirmed(order_id=self.order_id, confirmed_by=confirmed_by))

    @apply
    def on_placed(self, event: OrderPlaced):
        self.order_id = event.order_id
        self.total_amount = event.total_amount
        self.currency = event.currency
        self.status = "PLACED"

    @apply
    def on_confirmed(self, event: OrderConfirmed):
        self.status = "CONFIRMED"
        self.confirmed_by = event.confirmed_by


# Example usage
if __name__ == "__main__":  # pragma: no cover
    domain.init(traverse=False)

    with domain.domain_context():
        # Demonstrate upcaster transforms
        v1_data = {"order_id": "ORD-1", "amount": 99.99}
        v1_to_v2 = UpcastOrderPlacedV1ToV2()
        v2_data = v1_to_v2.upcast(dict(v1_data))
        print(f"v1 -> v2: {v2_data}")  # Added currency=USD

        v2_to_v3 = UpcastOrderPlacedV2ToV3()
        v3_data = v2_to_v3.upcast(dict(v2_data))
        print(f"v2 -> v3: {v3_data}")  # Renamed amount -> total_amount

        # Demonstrate confirmed event upcaster
        v1_confirmed = {
            "order_id": "ORD-1",
            "legacy_code": "LC-123",
            "operator_name": "Alice",
        }
        confirmed_upcaster = UpcastOrderConfirmedV1ToV2()
        v2_confirmed = confirmed_upcaster.upcast(dict(v1_confirmed))
        print(f"Confirmed v1 -> v2: {v2_confirmed}")  # Removed legacy_code, renamed

        # Normal aggregate usage
        order = Order.place(order_id="ORD-100", total_amount=250.00, currency="EUR")
        print(
            f"\nOrder: {order.order_id}, total={order.total_amount}, currency={order.currency}"
        )
        order.confirm(confirmed_by="Bob")
        print(f"Confirmed by: {order.confirmed_by}, status={order.status}")
