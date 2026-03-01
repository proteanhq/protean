"""Tests that HasOne/HasMany fields reject targets from a different aggregate cluster.

The guard lives in ``Domain._validate_domain()`` and fires during
``domain.init()``.  It ensures that associations only reference entities
within the same aggregate boundary — a core DDD invariant.
"""

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.entity import BaseEntity
from protean.exceptions import IncorrectUsageError
from protean.fields import HasMany, HasOne, Integer, Reference, String


# ── Domain elements ─────────────────────────────────────────────────────


class Order(BaseAggregate):
    name: String(max_length=100)
    items = HasMany("OrderItem")


class OrderItem(BaseEntity):
    sku: String(max_length=50)
    order = Reference(Order)


class Customer(BaseAggregate):
    name: String(max_length=100)
    addresses = HasMany("Address")


class Address(BaseEntity):
    city: String(max_length=100)
    customer = Reference(Customer)


# ── Tests ────────────────────────────────────────────────────────────────


class TestCrossAggregateHasManyGuard:
    @pytest.mark.no_test_domain
    def test_has_many_targeting_foreign_entity_raises(self):
        """An aggregate cannot HasMany an entity that belongs to another aggregate."""
        from protean import Domain

        domain = Domain(__name__, "Tests")

        class Invoice(BaseAggregate):
            total: Integer()
            # Points to OrderItem, which belongs to Order — not Invoice
            line_items = HasMany("OrderItem")

        domain.register(Order)
        domain.register(OrderItem, part_of=Order)
        domain.register(Invoice)

        with pytest.raises(IncorrectUsageError, match="different aggregate"):
            domain.init(traverse=False)

    def test_has_many_within_same_cluster_is_valid(self, test_domain):
        """An aggregate can HasMany an entity within its own cluster."""
        test_domain.register(Order)
        test_domain.register(OrderItem, part_of=Order)
        test_domain.init(traverse=False)  # Should not raise


class TestCrossAggregateHasOneGuard:
    @pytest.mark.no_test_domain
    def test_has_one_targeting_foreign_entity_raises(self):
        """An aggregate cannot HasOne an entity that belongs to another aggregate."""
        from protean import Domain

        domain = Domain(__name__, "Tests")

        class Warehouse(BaseAggregate):
            name: String(max_length=100)
            # Points to Address, which belongs to Customer — not Warehouse
            primary_address = HasOne("Address")

        domain.register(Customer)
        domain.register(Address, part_of=Customer)
        domain.register(Warehouse)

        with pytest.raises(IncorrectUsageError, match="different aggregate"):
            domain.init(traverse=False)

    def test_has_one_within_same_cluster_is_valid(self, test_domain):
        """An aggregate can HasOne an entity within its own cluster."""
        test_domain.register(Customer)
        test_domain.register(Address, part_of=Customer)
        test_domain.init(traverse=False)  # Should not raise


class TestCrossAggregateNestedEntityGuard:
    @pytest.mark.no_test_domain
    def test_nested_entity_with_has_one_to_foreign_entity_raises(self):
        """An entity cannot HasOne an entity from a different aggregate cluster."""
        from protean import Domain

        domain = Domain(__name__, "Tests")

        class Team(BaseAggregate):
            name: String(max_length=100)
            players = HasMany("Player")

        class Player(BaseEntity):
            name: String(max_length=100)
            # Points to Address, which belongs to Customer — not Team
            home_address = HasOne("Address")
            team = Reference(Team)

        domain.register(Team)
        domain.register(Player, part_of=Team)
        domain.register(Customer)
        domain.register(Address, part_of=Customer)

        with pytest.raises(IncorrectUsageError, match="different aggregate"):
            domain.init(traverse=False)

    @pytest.mark.no_test_domain
    def test_error_message_includes_context(self):
        """Error message should name the field, owner, target, and target's aggregate."""
        from protean import Domain

        domain = Domain(__name__, "Tests")

        class Shipment(BaseAggregate):
            name: String(max_length=100)
            # Points to OrderItem, which belongs to Order
            contents = HasMany("OrderItem")

        domain.register(Order)
        domain.register(OrderItem, part_of=Order)
        domain.register(Shipment)

        with pytest.raises(IncorrectUsageError) as exc_info:
            domain.init(traverse=False)

        error_msg = str(exc_info.value)
        assert "contents" in error_msg
        assert "Shipment" in error_msg
        assert "OrderItem" in error_msg
        assert "Order" in error_msg
