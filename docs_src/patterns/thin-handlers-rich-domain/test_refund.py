# --8<-- [start:tests]
from datetime import UTC, datetime, timedelta

import pytest
from refunds.domain import Order, RefundRequested

from protean.exceptions import ValidationError


class TestRefund:
    def test_can_refund_delivered_order(self, test_domain):
        order = Order(
            customer_id="cust-1",
            status="delivered",
            total=100.0,
            delivered_at=datetime.now(UTC),
        )

        order.request_refund(reason="Changed mind")

        assert order.status == "refund_requested"
        assert order.refund_amount == 100.0
        assert len(order._events) == 1
        assert isinstance(order._events[0], RefundRequested)

    def test_cannot_refund_draft_order(self, test_domain):
        order = Order(customer_id="cust-1", status="draft", total=100.0)

        with pytest.raises(ValidationError) as exc:
            order.request_refund(reason="Changed mind")

        assert "Only shipped or delivered orders" in str(exc.value)

    def test_refund_window_expired(self, test_domain):
        order = Order(
            customer_id="cust-1",
            status="delivered",
            total=100.0,
            delivered_at=datetime.now(UTC) - timedelta(days=31),
        )

        with pytest.raises(ValidationError) as exc:
            order.request_refund(reason="Changed mind")

        assert "Refund window has expired" in str(exc.value)

    def test_partial_refund_calculation(self, test_domain):
        order = Order(
            customer_id="cust-1",
            status="delivered",
            total=100.0,
            partial_refund_amount=30.0,
            delivered_at=datetime.now(UTC),
        )

        order.request_refund(amount=50.0, reason="Partial")

        assert order.refund_amount == 50.0

    def test_partial_refund_capped_at_remaining(self, test_domain):
        order = Order(
            customer_id="cust-1",
            status="delivered",
            total=100.0,
            partial_refund_amount=30.0,
            delivered_at=datetime.now(UTC),
        )

        order.request_refund(amount=200.0, reason="Full")

        assert order.refund_amount == 70.0  # Capped at remaining


# --8<-- [end:tests]
