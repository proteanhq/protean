"""Tests for ``assert_invalid`` and ``assert_valid`` helpers in ``protean.testing``.

Exercises validation assertion helpers across aggregates, entities,
and domain services.
"""

from uuid import uuid4

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.domain_service import BaseDomainService
from protean.core.entity import BaseEntity, invariant
from protean.core.event import BaseEvent
from protean.core.value_object import BaseValueObject
from protean.exceptions import ValidationError
from protean.fields import Float, HasMany, Identifier, Integer, String, ValueObject
from protean.testing import assert_invalid, assert_valid


# ---------------------------------------------------------------------------
# Domain elements
# ---------------------------------------------------------------------------
class OrderItem(BaseEntity):
    product_id = Identifier(required=True)
    quantity = Integer()
    price = Float()


class Warehouse(BaseValueObject):
    location = String()
    contact = String()


class Order(BaseAggregate):
    customer_id = Identifier(required=True)
    items = HasMany("OrderItem")
    status = String(default="PENDING")
    payment_id = Identifier()

    @invariant.post
    def order_should_contain_items(self):
        if not self.items or len(self.items) == 0:
            raise ValidationError({"_entity": ["Order must contain at least one item"]})


class Inventory(BaseAggregate):
    product_id = Identifier(required=True)
    quantity = Integer()
    warehouse = ValueObject(Warehouse)

    def reserve_stock(self, quantity: int):
        self.quantity -= quantity


class OrderPlacementService(BaseDomainService):
    def __init__(self, order, inventories):
        super().__init__(order, inventories)
        self.order = order
        self.inventories = inventories

    @invariant.pre
    def inventory_should_have_sufficient_stock(self):
        for item in self.order.items:
            inventory = next(
                (i for i in self.inventories if i.product_id == item.product_id), None
            )
            if inventory is None or inventory.quantity < item.quantity:
                raise ValidationError({"_service": ["Product is out of stock"]})

    @invariant.pre
    def order_payment_method_should_be_valid(self):
        if not self.order.payment_id:
            raise ValidationError(
                {"_service": ["Order must have a valid payment method"]}
            )

    def __call__(self):
        for item in self.order.items:
            inventory = next(
                (i for i in self.inventories if i.product_id == item.product_id), None
            )
            inventory.reserve_stock(item.quantity)
        self.order.status = "CONFIRMED"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Order)
    test_domain.register(OrderItem, part_of=Order)
    test_domain.register(Inventory)
    test_domain.register(Warehouse, part_of=Inventory)
    test_domain.register(OrderPlacementService, part_of=[Order, Inventory])
    test_domain.init(traverse=False)


# ---------------------------------------------------------------------------
# Tests: assert_invalid
# ---------------------------------------------------------------------------
class TestAssertInvalid:
    def test_catches_validation_error(self):
        """assert_invalid catches ValidationError from domain services."""
        pid = str(uuid4())
        order = Order(
            customer_id=str(uuid4()),
            payment_id=str(uuid4()),
            items=[OrderItem(product_id=pid, quantity=10, price=100)],
        )
        inventory = Inventory(
            product_id=pid,
            quantity=5,
            warehouse=Warehouse(location="NYC", contact="John"),
        )

        exc = assert_invalid(
            lambda: OrderPlacementService(order, [inventory])(),
            message="Product is out of stock",
        )
        assert isinstance(exc, ValidationError)

    def test_catches_aggregate_validation_error(self):
        """assert_invalid catches ValidationError from aggregate invariants."""
        exc = assert_invalid(
            lambda: Order(customer_id=str(uuid4()), items=[]),
            message="Order must contain at least one item",
        )
        assert isinstance(exc, ValidationError)

    def test_returns_validation_error(self):
        """assert_invalid returns the caught ValidationError."""
        exc = assert_invalid(
            lambda: Order(customer_id=str(uuid4()), items=[]),
        )
        assert isinstance(exc, ValidationError)
        assert "Order must contain at least one item" in str(exc)

    def test_without_message_check(self):
        """assert_invalid works without a message argument."""
        pid = str(uuid4())
        order = Order(
            customer_id=str(uuid4()),
            payment_id=str(uuid4()),
            items=[OrderItem(product_id=pid, quantity=10, price=100)],
        )
        inventory = Inventory(
            product_id=pid,
            quantity=5,
            warehouse=Warehouse(location="NYC", contact="John"),
        )

        exc = assert_invalid(
            lambda: OrderPlacementService(order, [inventory])()
        )
        assert isinstance(exc, ValidationError)

    def test_raises_when_no_error(self):
        """assert_invalid raises AssertionError when no ValidationError occurs."""
        pid = str(uuid4())
        order = Order(
            customer_id=str(uuid4()),
            payment_id=str(uuid4()),
            items=[OrderItem(product_id=pid, quantity=5, price=100)],
        )
        inventory = Inventory(
            product_id=pid,
            quantity=100,
            warehouse=Warehouse(location="NYC", contact="John"),
        )

        with pytest.raises(AssertionError, match="Expected ValidationError"):
            assert_invalid(
                lambda: OrderPlacementService(order, [inventory])()
            )

    def test_raises_when_message_not_found(self):
        """assert_invalid raises AssertionError when message doesn't match."""
        pid = str(uuid4())
        order = Order(
            customer_id=str(uuid4()),
            payment_id=str(uuid4()),
            items=[OrderItem(product_id=pid, quantity=10, price=100)],
        )
        inventory = Inventory(
            product_id=pid,
            quantity=5,
            warehouse=Warehouse(location="NYC", contact="John"),
        )

        with pytest.raises(AssertionError, match="Expected validation message"):
            assert_invalid(
                lambda: OrderPlacementService(order, [inventory])(),
                message="Completely wrong message",
            )

    def test_multiple_pre_invariant_violations(self):
        """assert_invalid detects multiple pre-invariant violations."""
        pid = str(uuid4())
        order = Order(
            customer_id=str(uuid4()),
            payment_id=None,  # No payment method
            items=[OrderItem(product_id=pid, quantity=10, price=100)],
        )
        inventory = Inventory(
            product_id=pid,
            quantity=5,  # Insufficient stock
            warehouse=Warehouse(location="NYC", contact="John"),
        )

        exc = assert_invalid(
            lambda: OrderPlacementService(order, [inventory])(),
            message="Product is out of stock",
        )
        # Both errors are captured in the same ValidationError
        assert "Product is out of stock" in str(exc)
        assert "Order must have a valid payment method" in str(exc)


# ---------------------------------------------------------------------------
# Tests: assert_valid
# ---------------------------------------------------------------------------
class TestAssertValid:
    def test_passes_for_valid_operation(self):
        """assert_valid passes when no ValidationError is raised."""
        pid = str(uuid4())
        order = Order(
            customer_id=str(uuid4()),
            payment_id=str(uuid4()),
            items=[OrderItem(product_id=pid, quantity=5, price=100)],
        )
        inventory = Inventory(
            product_id=pid,
            quantity=100,
            warehouse=Warehouse(location="NYC", contact="John"),
        )

        assert_valid(lambda: OrderPlacementService(order, [inventory])())

    def test_returns_operation_result(self):
        """assert_valid returns the operation's return value."""
        result = assert_valid(lambda: 42)
        assert result == 42

    def test_raises_on_validation_error(self):
        """assert_valid raises AssertionError when a ValidationError occurs."""
        pid = str(uuid4())
        order = Order(
            customer_id=str(uuid4()),
            payment_id=str(uuid4()),
            items=[OrderItem(product_id=pid, quantity=10, price=100)],
        )
        inventory = Inventory(
            product_id=pid,
            quantity=5,
            warehouse=Warehouse(location="NYC", contact="John"),
        )

        with pytest.raises(AssertionError, match="Expected no ValidationError"):
            assert_valid(lambda: OrderPlacementService(order, [inventory])())

    def test_valid_aggregate_creation(self):
        """assert_valid works for aggregate construction."""
        pid = str(uuid4())
        order = assert_valid(
            lambda: Order(
                customer_id=str(uuid4()),
                items=[OrderItem(product_id=pid, quantity=1, price=10)],
            )
        )
        assert order is not None
        assert order.status == "PENDING"

    def test_error_message_includes_details(self):
        """assert_valid error message includes validation error details."""
        with pytest.raises(AssertionError, match="Order must contain at least one item"):
            assert_valid(
                lambda: Order(customer_id=str(uuid4()), items=[])
            )
