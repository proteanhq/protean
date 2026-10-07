"""
Event versioning for schema evolution.

This example demonstrates:
- Using the __version__ class attribute for event versioning
- Backward compatible changes (same version, optional fields)
- Breaking changes (new version, plus an upcaster for each older version)
- Reading the version from an event's metadata
- Upcasting an old stored payload to the current schema

An event keeps one class name across versions. The class always describes the
current schema. Each older version gets an upcaster that turns a stored payload
of that version into the next one. The framework chains the upcasters and
applies them when it reads an old event.

Usage:
    event = OrderPlaced(
        order_id="ORD-001",
        customer_id="CUST-123",
        placed_at=datetime.now(UTC),
        total=Money(amount=99.99, currency="USD"),
        items=[],
    )
    event._metadata.domain.version  # 3
"""

from datetime import UTC, datetime

from protean import Domain
from protean.core.upcaster import BaseUpcaster
from protean.fields import DateTime, Float, List, String, ValueObject

# Domain setup
domain = Domain()


@domain.value_object
class Money:
    """Value object for monetary amounts."""

    amount: Float(required=True)
    currency: String(max_length=3, default="USD")


# Aggregates (required for events to reference)
@domain.aggregate
class Order:
    """Order aggregate."""

    order_id: String(required=True, identifier=True)


@domain.aggregate
class Product:
    """Product aggregate."""

    product_id: String(required=True, identifier=True)


@domain.aggregate
class User:
    """User aggregate."""

    user_id: String(required=True, identifier=True)


@domain.aggregate
class Account:
    """Account aggregate."""

    account_id: String(required=True, identifier=True)


# Example: an event that went through two breaking changes
@domain.event(part_of="Order")
class OrderPlaced:
    """Order placement event.

    Version History:
    - v1: order_id, customer_id, placed_at
    - v2: added optional total
    - v3: made total required, added items (BREAKING)
    """

    __version__ = 3

    order_id: String(required=True, identifier=True)
    customer_id: String(required=True)
    placed_at: DateTime(required=True)
    total = ValueObject(Money, required=True)
    items: List()


@domain.upcaster(event_type=OrderPlaced, from_version=1, to_version=2)
class UpcastOrderPlacedV1ToV2(BaseUpcaster):
    """v1 had no total. v2 added it as an optional field."""

    def upcast(self, data: dict) -> dict:
        data.setdefault("total", None)
        return data


@domain.upcaster(event_type=OrderPlaced, from_version=2, to_version=3)
class UpcastOrderPlacedV2ToV3(BaseUpcaster):
    """v3 requires total and adds items."""

    def upcast(self, data: dict) -> dict:
        if data.get("total") is None:
            data["total"] = {"amount": 0.0, "currency": "USD"}
        data.setdefault("items", [])
        return data


# Example: evolving from a primitive to a value object
@domain.event(part_of="Product")
class PriceChanged:
    """Price change event.

    Version History:
    - v1: old_price and new_price as floats
    - v2: old_price and new_price as Money value objects (BREAKING)
    """

    __version__ = 2

    product_id: String(required=True, identifier=True)
    old_price = ValueObject(Money, required=True)
    new_price = ValueObject(Money, required=True)
    changed_at: DateTime(required=True)


@domain.upcaster(event_type=PriceChanged, from_version=1, to_version=2)
class UpcastPriceChangedV1ToV2(BaseUpcaster):
    """v1 prices were plain floats in USD."""

    def upcast(self, data: dict) -> dict:
        data["old_price"] = {"amount": data["old_price"], "currency": "USD"}
        data["new_price"] = {"amount": data["new_price"], "currency": "USD"}
        return data


# Example: adding optional enrichment fields keeps the same version
@domain.event(part_of="User")
class UserRegistered:
    """User registration event.

    Version History:
    - v1: user_id, email, registered_at
    - v1: added optional user_agent, ip_address, referral_source
      (backward compatible, no version bump)
    """

    __version__ = 1

    user_id: String(required=True, identifier=True)
    email: String(required=True)
    registered_at: DateTime(required=True)

    # Optional enrichment fields - old events simply lack them
    user_agent: String()
    ip_address: String()
    referral_source: String()


# Example: field removal (breaking change)
@domain.event(part_of="Account")
class AccountCreated:
    """Account creation event.

    Version History:
    - v1: account_id, username, email, created_at
    - v2: removed username (BREAKING)
    """

    __version__ = 2

    account_id: String(required=True, identifier=True)
    email: String(required=True)  # Now the primary identifier
    created_at: DateTime(required=True)


@domain.upcaster(event_type=AccountCreated, from_version=1, to_version=2)
class UpcastAccountCreatedV1ToV2(BaseUpcaster):
    """v2 dropped username."""

    def upcast(self, data: dict) -> dict:
        data.pop("username", None)
        return data


# Example usage
if __name__ == "__main__":
    domain.init(traverse=False)

    with domain.domain_context():
        print("Event Versioning Examples\n")

        # Current version: the version comes from the class attribute
        order = OrderPlaced(
            order_id="ORD-001",
            customer_id="CUST-123",
            placed_at=datetime.now(UTC),
            total=Money(amount=149.99, currency="USD"),
            items=[
                {"product_id": "PROD-001", "quantity": 2},
                {"product_id": "PROD-002", "quantity": 1},
            ],
        )

        print("OrderPlaced (current):")
        print(f"  Version: {order._metadata.domain.version}")
        print(f"  Type: {order._metadata.headers.type}")
        print(f"  Total: {order.total.amount} {order.total.currency}")

        # A stored v1 payload, upcast step by step to v3
        v1_payload = {
            "order_id": "ORD-000",
            "customer_id": "CUST-123",
            "placed_at": datetime.now(UTC).isoformat(),
        }
        v2_payload = UpcastOrderPlacedV1ToV2().upcast(dict(v1_payload))
        v3_payload = UpcastOrderPlacedV2ToV3().upcast(v2_payload)
        old_order = OrderPlaced(**v3_payload)

        print("\nOrderPlaced v1 payload upcast to v3:")
        print(f"  Total (defaulted): {old_order.total.amount}")
        print(f"  Items (defaulted): {old_order.items}")

        # Primitive to value object evolution
        old_price = UpcastPriceChangedV1ToV2().upcast(
            {
                "product_id": "PROD-100",
                "old_price": 29.99,
                "new_price": 24.99,
                "changed_at": datetime.now(UTC).isoformat(),
            }
        )
        price = PriceChanged(**old_price)

        print("\nPriceChanged v1 payload upcast to v2:")
        print(f"  New price: {price.new_price.amount} {price.new_price.currency}")

        # Optional enrichment fields: same version, old and new payloads both work
        basic = UserRegistered(
            user_id="USER-001",
            email="john@example.com",
            registered_at=datetime.now(UTC),
        )
        enriched = UserRegistered(
            user_id="USER-002",
            email="jane@example.com",
            registered_at=datetime.now(UTC),
            user_agent="Mozilla/5.0",
            ip_address="192.168.1.100",
            referral_source="google",
        )

        print("\nUserRegistered with enrichment (still v1):")
        print(f"  Basic: {basic.email}, IP: {basic.ip_address}")
        print(f"  Enriched: {enriched.email}, IP: {enriched.ip_address}")

        # Field removal
        account = AccountCreated(
            **UpcastAccountCreatedV1ToV2().upcast(
                {
                    "account_id": "ACC-001",
                    "username": "jdoe",
                    "email": "jdoe@example.com",
                    "created_at": datetime.now(UTC).isoformat(),
                }
            )
        )

        print("\nAccountCreated v1 payload upcast to v2:")
        print(f"  Email: {account.email}")
