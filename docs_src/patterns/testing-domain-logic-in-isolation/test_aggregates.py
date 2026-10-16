# --8<-- [start:placement]
import pytest
from isolation_shop.domain import (
    Account,
    Order,
    OrderCancelled,
    OrderItem,
    OrderPlaced,
    ShipmentInterceptRequested,
)

from protean.exceptions import ValidationError


class TestOrderPlacement:
    def test_placing_a_draft_order(self):
        order = Order(
            customer_id="cust-123",
            status="draft",
            total=50.0,
        )
        order.add_items(
            OrderItem(
                product_id="prod-1",
                quantity=2,
                unit_price=25.0,
            )
        )

        order.place()

        assert order.status == "placed"
        assert order.placed_at is not None

    def test_placing_an_already_placed_order_fails(self):
        order = Order(
            customer_id="cust-123",
            status="placed",
            total=50.0,
            items=[OrderItem(product_id="prod-1", quantity=2, unit_price=25.0)],
        )

        with pytest.raises(ValidationError) as exc:
            order.place()

        assert "Only draft orders can be placed" in str(exc.value)
        assert order.status == "placed"  # State unchanged


# --8<-- [end:placement]


# --8<-- [start:account_rules]
class TestAccountWithdrawal:
    def test_successful_withdrawal(self):
        account = Account(balance=1000.0, overdraft_limit=50.0)

        account.withdraw(200.0)

        assert account.balance == 800.0

    def test_withdrawal_respects_overdraft_limit(self):
        account = Account(balance=100.0, overdraft_limit=50.0)

        # Can withdraw up to balance + overdraft
        account.withdraw(150.0)
        assert account.balance == -50.0

    def test_withdrawal_exceeding_overdraft_fails(self):
        account = Account(balance=100.0, overdraft_limit=50.0)

        with pytest.raises(ValidationError) as exc:
            account.withdraw(200.0)

        assert "Insufficient funds" in str(exc.value)
        assert account.balance == 100.0  # State unchanged

    def test_negative_withdrawal_fails(self):
        account = Account(balance=1000.0)

        with pytest.raises(ValidationError) as exc:
            account.withdraw(-50.0)

        assert "must be positive" in str(exc.value)

    def test_withdrawal_from_frozen_account_fails(self):
        account = Account(balance=1000.0, status="frozen")

        with pytest.raises(ValidationError) as exc:
            account.withdraw(100.0)

        assert "non-active account" in str(exc.value)


# --8<-- [end:account_rules]


# --8<-- [start:events]
class TestOrderEvents:
    def test_placing_order_raises_order_placed(self):
        order = Order(
            customer_id="cust-123",
            total=100.0,
        )
        order.add_items(
            OrderItem(
                product_id="prod-1",
                quantity=1,
                unit_price=100.0,
            )
        )

        order.place()

        assert len(order._events) == 1
        event = order._events[0]
        assert isinstance(event, OrderPlaced)
        assert event.order_id == order.order_id
        assert event.customer_id == "cust-123"
        assert event.total == 100.0

    def test_cancelling_shipped_order_raises_shipment_intercept(self):
        order = Order(
            customer_id="cust-123",
            status="shipped",
            tracking_number="TRK-789",
        )

        order.cancel("Customer changed mind")

        events = order._events
        assert len(events) == 2
        assert isinstance(events[0], OrderCancelled)
        assert isinstance(events[1], ShipmentInterceptRequested)
        assert events[1].tracking_number == "TRK-789"

    def test_no_event_raised_when_operation_fails(self):
        order = Order(customer_id="cust-123", status="draft")

        with pytest.raises(ValidationError):
            order.ship("TRK-123")

        assert len(order._events) == 0  # No events on failure


# --8<-- [end:events]
