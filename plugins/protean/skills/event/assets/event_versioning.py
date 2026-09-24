"""
Event versioning for schema evolution.

This example demonstrates:
- Using __version__ attribute for event versioning
- Backward compatible changes (same version)
- Breaking changes (new version required)
- Version migration strategies
- Handling multiple event versions

Usage:
    # Version 1
    event_v1 = OrderPlaced(
        order_id="ORD-001",
        customer_id="CUST-123"
    )

    # Version 2 with additional fields
    event_v2 = OrderPlaced(
        order_id="ORD-001",
        customer_id="CUST-123",
        total=Money(amount=99.99, currency="USD")
    )
"""

from datetime import UTC, datetime

from protean import Domain
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


# Version 1 - Original event
@domain.event(part_of="Order")
class OrderPlacedV1:
    """Original version of OrderPlaced event.

    Version History:
    - v1: Initial version with basic order info (2024-01-01)
    """

    __version__ = 1

    order_id: String(required=True, identifier=True)
    customer_id: String(required=True)
    placed_at: DateTime(required=True)


# Version 2 - Added optional fields (backward compatible)
@domain.event(part_of="Order")
class OrderPlacedV2Compatible:
    """OrderPlaced v2 with backward compatible changes.

    Version History:
    - v1: Initial version
    - v2: Added optional total field (backward compatible)
    """

    __version__ = 2

    order_id: String(required=True, identifier=True)
    customer_id: String(required=True)
    placed_at: DateTime(required=True)

    # New optional field - backward compatible
    # Old v1 events won't have this field (will be None)
    total = ValueObject(Money)


# Version 3 - Breaking change (required field added)
@domain.event(part_of="Order")
class OrderPlacedV3Breaking:
    """OrderPlaced v3 with breaking changes.

    Version History:
    - v1: Initial version
    - v2: Added optional total field
    - v3: Made total required, added items (BREAKING)
    """

    __version__ = 3

    order_id: String(required=True, identifier=True)
    customer_id: String(required=True)
    placed_at: DateTime(required=True)

    # Now required - breaking change from v2
    total = ValueObject(Money, required=True)

    # New required field - breaking change
    items: List()


# Example: Evolving from primitive to value object
@domain.event(part_of="Product")
class PriceChangedV1:
    """Version 1 - using primitive float for price."""

    __version__ = 1

    product_id: String(required=True, identifier=True)
    old_price: Float(required=True)
    new_price: Float(required=True)
    changed_at: DateTime(required=True)


@domain.event(part_of="Product")
class PriceChangedV2:
    """Version 2 - using Money value object for price."""

    __version__ = 2

    product_id: String(required=True, identifier=True)
    old_price = ValueObject(Money, required=True)
    new_price = ValueObject(Money, required=True)
    changed_at: DateTime(required=True)


# Example: Adding optional enrichment fields
@domain.event(part_of="User")
class UserRegisteredV1:
    """Version 1 - basic user registration."""

    __version__ = 1

    user_id: String(required=True, identifier=True)
    email: String(required=True)
    registered_at: DateTime(required=True)


@domain.event(part_of="User")
class UserRegisteredV2:
    """Version 2 - added optional tracking fields (backward compatible)."""

    __version__ = 2

    user_id: String(required=True, identifier=True)
    email: String(required=True)
    registered_at: DateTime(required=True)

    # Optional enrichment fields - backward compatible
    user_agent: String()
    ip_address: String()
    referral_source: String()


# Example: Field removal (breaking change)
@domain.event(part_of="Account")
class AccountCreatedV1:
    """Version 1 - with username field."""

    __version__ = 1

    account_id: String(required=True, identifier=True)
    username: String(required=True)
    email: String(required=True)
    created_at: DateTime(required=True)


@domain.event(part_of="Account")
class AccountCreatedV2:
    """Version 2 - removed username (breaking change)."""

    __version__ = 2

    account_id: String(required=True, identifier=True)
    email: String(required=True)  # Now the primary identifier
    created_at: DateTime(required=True)
    # username field removed


# Example usage
if __name__ == "__main__":
    domain.init(traverse=False)

    with domain.domain_context():
        print("Event Versioning Examples\n")

        # Version 1 - Original
        order_v1 = OrderPlacedV1(
            order_id="ORD-001",
            customer_id="CUST-123",
            placed_at=datetime.now(UTC),
        )

        print("OrderPlaced v1:")
        print(f"  Version: {order_v1.__version__}")
        print(f"  Order ID: {order_v1.order_id}")
        print(f"  Has total field: {hasattr(order_v1, 'total')}")

        # Version 2 - Backward compatible (optional field)
        order_v2_without_total = OrderPlacedV2Compatible(
            order_id="ORD-002",
            customer_id="CUST-123",
            placed_at=datetime.now(UTC),
        )

        order_v2_with_total = OrderPlacedV2Compatible(
            order_id="ORD-003",
            customer_id="CUST-123",
            placed_at=datetime.now(UTC),
            total=Money(amount=99.99, currency="USD"),
        )

        print("\nOrderPlaced v2 (backward compatible):")
        print(f"  Version: {order_v2_with_total.__version__}")
        print(f"  Without total: total={order_v2_without_total.total}")
        print(
            f"  With total: total={order_v2_with_total.total.amount} "
            f"{order_v2_with_total.total.currency}"
        )

        # Version 3 - Breaking change (required field)
        order_v3 = OrderPlacedV3Breaking(
            order_id="ORD-004",
            customer_id="CUST-123",
            placed_at=datetime.now(UTC),
            total=Money(amount=149.99, currency="USD"),
            items=[
                {"product_id": "PROD-001", "quantity": 2},
                {"product_id": "PROD-002", "quantity": 1},
            ],
        )

        print("\nOrderPlaced v3 (breaking change):")
        print(f"  Version: {order_v3.__version__}")
        print(f"  Total (required): {order_v3.total.amount}")
        print(f"  Items (required): {len(order_v3.items)} items")

        # Primitive to Value Object evolution
        price_v1 = PriceChangedV1(
            product_id="PROD-100",
            old_price=29.99,
            new_price=24.99,
            changed_at=datetime.now(UTC),
        )

        price_v2 = PriceChangedV2(
            product_id="PROD-100",
            old_price=Money(amount=29.99, currency="USD"),
            new_price=Money(amount=24.99, currency="USD"),
            changed_at=datetime.now(UTC),
        )

        print("\nPriceChanged evolution:")
        print(f"  V1 (primitive): {price_v1.new_price}")
        print(
            f"  V2 (value object): {price_v2.new_price.amount} {price_v2.new_price.currency}"
        )

        # Optional enrichment fields
        user_v1 = UserRegisteredV1(
            user_id="USER-001",
            email="john@example.com",
            registered_at=datetime.now(UTC),
        )

        user_v2 = UserRegisteredV2(
            user_id="USER-002",
            email="jane@example.com",
            registered_at=datetime.now(UTC),
            user_agent="Mozilla/5.0",
            ip_address="192.168.1.100",
            referral_source="google",
        )

        print("\nUserRegistered with enrichment:")
        print(f"  V1 basic: {user_v1.email}")
        print(f"  V2 enriched: {user_v2.email}, IP: {user_v2.ip_address}")
