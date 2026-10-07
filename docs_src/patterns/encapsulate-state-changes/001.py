# --8<-- [start:after]
from datetime import UTC, datetime

from protean import Domain, current_domain, handle
from protean.core.command_handler import BaseCommandHandler
from protean.exceptions import ValidationError
from protean.fields import Auto, DateTime, Float, HasMany, Identifier, Integer, String

domain = Domain(name="EncapsulateStateChangesOrders")


@domain.entity(part_of="Order")
class OrderItem:
    product_id: Identifier(required=True)
    quantity: Integer(min_value=1)
    unit_price: Float()


@domain.event(part_of="Order")
class OrderShipped:
    order_id: Identifier(required=True)
    customer_id: Identifier(required=True)
    tracking_number: String(required=True)


@domain.event(part_of="Order")
class OrderCancelled:
    order_id: Identifier(required=True)
    customer_id: Identifier(required=True)
    reason: String()


@domain.event(part_of="Order")
class OrderPaid:
    order_id: Identifier(required=True)
    customer_id: Identifier(required=True)
    total: Float()


@domain.command(part_of="Order")
class ShipOrder:
    order_id: Identifier(required=True)
    tracking_number: String(required=True)


@domain.command(part_of="Order")
class CancelOrder:
    order_id: Identifier(required=True)
    reason: String()


@domain.command(part_of="Order")
class PayOrder:
    order_id: Identifier(required=True)


@domain.aggregate
class Order:
    order_id: Auto(identifier=True)
    customer_id: Identifier(required=True)
    items = HasMany(OrderItem)
    status: String(default="draft")
    total: Float(default=0.0)
    shipped_at: DateTime()
    tracking_number: String()
    cancelled_at: DateTime()
    cancellation_reason: String()

    def ship(self, tracking_number: str) -> None:
        """Ship this order with the given tracking number."""
        if self.status != "paid":
            raise ValidationError({"status": ["Only paid orders can be shipped"]})

        if not self.items:
            raise ValidationError({"items": ["Cannot ship an order with no items"]})

        self.status = "shipped"
        self.shipped_at = datetime.now(UTC)
        self.tracking_number = tracking_number

        self.raise_(
            OrderShipped(
                order_id=self.order_id,
                customer_id=self.customer_id,
                tracking_number=tracking_number,
            )
        )

    def cancel(self, reason: str) -> None:
        """Cancel this order with the given reason."""
        if self.status in ("shipped", "cancelled"):
            raise ValidationError(
                {"status": ["Cannot cancel a shipped or already cancelled order"]}
            )

        self.status = "cancelled"
        self.cancelled_at = datetime.now(UTC)
        self.cancellation_reason = reason

        self.raise_(
            OrderCancelled(
                order_id=self.order_id,
                customer_id=self.customer_id,
                reason=reason,
            )
        )

    def pay(self) -> None:
        """Mark this order as paid."""
        if self.status != "draft":
            raise ValidationError({"status": ["Only draft orders can be paid"]})

        self.status = "paid"

        self.raise_(
            OrderPaid(
                order_id=self.order_id,
                customer_id=self.customer_id,
                total=self.total,
            )
        )


@domain.command_handler(part_of=Order)
class OrderCommandHandler(BaseCommandHandler):
    @handle(ShipOrder)
    def ship_order(self, command: ShipOrder):
        repo = current_domain.repository_for(Order)
        order = repo.get(command.order_id)
        order.ship(command.tracking_number)
        repo.add(order)

    @handle(CancelOrder)
    def cancel_order(self, command: CancelOrder):
        repo = current_domain.repository_for(Order)
        order = repo.get(command.order_id)
        order.cancel(command.reason)
        repo.add(order)

    @handle(PayOrder)
    def pay_order(self, command: PayOrder):
        repo = current_domain.repository_for(Order)
        order = repo.get(command.order_id)
        order.pay()
        repo.add(order)


# --8<-- [end:after]

import pytest


@pytest.fixture
def test_domain():
    domain.init(traverse=False)
    with domain.domain_context():
        yield domain


# --8<-- [start:tests]
class TestOrderShipping:
    def test_shipping_a_paid_order(self, test_domain):
        order = Order(
            customer_id="cust-1",
            items=[OrderItem(product_id="prod-1", quantity=1, unit_price=10.0)],
            status="paid",
        )

        order.ship(tracking_number="TRK-123")

        assert order.status == "shipped"
        assert order.tracking_number == "TRK-123"
        assert order.shipped_at is not None
        assert len(order._events) == 1
        assert isinstance(order._events[0], OrderShipped)

    def test_cannot_ship_unpaid_order(self, test_domain):
        order = Order(
            customer_id="cust-1",
            items=[OrderItem(product_id="prod-1", quantity=1, unit_price=10.0)],
            status="draft",
        )

        with pytest.raises(ValidationError) as exc:
            order.ship(tracking_number="TRK-123")

        assert "Only paid orders can be shipped" in str(exc.value)
        assert order.status == "draft"  # State unchanged

    def test_cannot_ship_empty_order(self, test_domain):
        order = Order(customer_id="cust-1", status="paid")

        with pytest.raises(ValidationError) as exc:
            order.ship(tracking_number="TRK-123")

        assert "Cannot ship an order with no items" in str(exc.value)


# --8<-- [end:tests]
