# --8<-- [start:states]
from enum import Enum


class OrderStatus(Enum):
    DRAFT = "draft"
    PLACED = "placed"
    PAID = "paid"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"
    REFUNDED = "refunded"


# --8<-- [end:states]

# --8<-- [start:aggregate]
from datetime import UTC, datetime

from protean import Domain
from protean.exceptions import ValidationError
from protean.fields import Auto, DateTime, Float, Identifier, String

domain = Domain(name="OrderStateMachine")


@domain.event(part_of="Order")
class OrderPlaced:
    order_id = Identifier(required=True)
    customer_id = Identifier(required=True)
    total = Float()


@domain.event(part_of="Order")
class OrderPaid:
    order_id = Identifier(required=True)
    customer_id = Identifier(required=True)
    total = Float()


@domain.event(part_of="Order")
class OrderShipped:
    order_id = Identifier(required=True)
    tracking_number = String()


@domain.event(part_of="Order")
class OrderDelivered:
    order_id = Identifier(required=True)
    delivered_at = DateTime()


@domain.event(part_of="Order")
class OrderCancelled:
    order_id = Identifier(required=True)
    reason = String()


@domain.event(part_of="Order")
class OrderRefunded:
    order_id = Identifier(required=True)
    refund_amount = Float()


# --8<-- [start:status_field]
@domain.aggregate
class Order:
    status = String(
        choices=OrderStatus,
        default=OrderStatus.DRAFT.value,
    )
    # --8<-- [end:status_field]
    order_id = Auto(identifier=True)
    customer_id = Identifier(required=True)
    total = Float(default=0.0)
    tracking_number = String()
    shipped_at = DateTime()
    delivered_at = DateTime()
    cancelled_at = DateTime()
    cancellation_reason = String()
    refunded_at = DateTime()

    # --- Transition: draft → placed ---

    def place(self) -> None:
        """Place this order, moving it from draft to placed."""
        if self.status != OrderStatus.DRAFT.value:
            raise ValidationError(
                {"status": [f"Cannot place an order in '{self.status}' status"]}
            )

        self.status = OrderStatus.PLACED.value

        self.raise_(
            OrderPlaced(
                order_id=self.order_id,
                customer_id=self.customer_id,
                total=self.total,
            )
        )

    # --- Transition: placed → paid ---

    def pay(self) -> None:
        """Record payment, moving the order from placed to paid."""
        if self.status != OrderStatus.PLACED.value:
            raise ValidationError(
                {"status": [f"Cannot pay an order in '{self.status}' status"]}
            )

        self.status = OrderStatus.PAID.value

        self.raise_(
            OrderPaid(
                order_id=self.order_id,
                customer_id=self.customer_id,
                total=self.total,
            )
        )

    # --- Transition: paid → shipped ---

    def ship(self, tracking_number: str) -> None:
        """Ship this order with the given tracking number."""
        if self.status != OrderStatus.PAID.value:
            raise ValidationError(
                {"status": [f"Cannot ship an order in '{self.status}' status"]}
            )

        self.status = OrderStatus.SHIPPED.value
        self.tracking_number = tracking_number
        self.shipped_at = datetime.now(UTC)

        self.raise_(
            OrderShipped(
                order_id=self.order_id,
                tracking_number=tracking_number,
            )
        )

    # --- Transition: shipped → delivered ---

    def deliver(self) -> None:
        """Mark this order as delivered."""
        if self.status != OrderStatus.SHIPPED.value:
            raise ValidationError(
                {"status": [f"Cannot deliver an order in '{self.status}' status"]}
            )

        self.status = OrderStatus.DELIVERED.value
        self.delivered_at = datetime.now(UTC)

        self.raise_(
            OrderDelivered(
                order_id=self.order_id,
                delivered_at=self.delivered_at,
            )
        )

    # --- Transition: draft|placed → cancelled ---

    def cancel(self, reason: str) -> None:
        """Cancel this order. Only draft or placed orders can be cancelled."""
        allowed = {OrderStatus.DRAFT.value, OrderStatus.PLACED.value}
        if self.status not in allowed:
            raise ValidationError(
                {
                    "status": [
                        (
                            f"Cannot cancel an order in '{self.status}' status; "
                            "only draft or placed orders can be cancelled"
                        )
                    ]
                }
            )

        self.status = OrderStatus.CANCELLED.value
        self.cancelled_at = datetime.now(UTC)
        self.cancellation_reason = reason

        self.raise_(
            OrderCancelled(
                order_id=self.order_id,
                reason=reason,
            )
        )

    # --- Transition: paid → refunded ---

    def refund(self) -> None:
        """Refund this order. Only paid orders can be refunded."""
        if self.status != OrderStatus.PAID.value:
            raise ValidationError(
                {"status": [f"Cannot refund an order in '{self.status}' status"]}
            )

        self.status = OrderStatus.REFUNDED.value
        self.refunded_at = datetime.now(UTC)

        self.raise_(
            OrderRefunded(
                order_id=self.order_id,
                refund_amount=self.total,
            )
        )


# --8<-- [end:aggregate]

# --8<-- [start:handlers]
from protean import current_domain, handle


@domain.command(part_of=Order)
class PlaceOrder:
    order_id = Identifier(required=True)


@domain.command(part_of=Order)
class ShipOrder:
    order_id = Identifier(required=True)
    tracking_number = String(required=True)


@domain.command(part_of=Order)
class CancelOrder:
    order_id = Identifier(required=True)
    reason = String()


@domain.command_handler(part_of=Order)
class OrderCommandHandler:
    @handle(PlaceOrder)
    def place_order(self, command: PlaceOrder):
        repo = current_domain.repository_for(Order)
        order = repo.get(command.order_id)
        order.place()
        repo.add(order)

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


# --8<-- [end:handlers]

# --8<-- [start:tests]
import pytest


class TestOrderStateMachine:
    def test_place_draft_order(self, test_domain):
        order = Order(customer_id="cust-1", total=99.99)

        order.place()

        assert order.status == OrderStatus.PLACED.value
        assert len(order._events) == 1
        assert isinstance(order._events[0], OrderPlaced)

    def test_cannot_place_already_placed_order(self, test_domain):
        order = Order(customer_id="cust-1", status=OrderStatus.PLACED.value)

        with pytest.raises(ValidationError) as exc:
            order.place()

        assert "Cannot place an order in 'placed' status" in str(exc.value)

    def test_full_happy_path(self, test_domain):
        order = Order(customer_id="cust-1", total=49.99)

        order.place()
        assert order.status == OrderStatus.PLACED.value

        order.pay()
        assert order.status == OrderStatus.PAID.value

        order.ship(tracking_number="TRK-001")
        assert order.status == OrderStatus.SHIPPED.value

        order.deliver()
        assert order.status == OrderStatus.DELIVERED.value

    def test_cannot_ship_cancelled_order(self, test_domain):
        order = Order(customer_id="cust-1", status=OrderStatus.PLACED.value)
        order.cancel(reason="Customer changed mind")

        with pytest.raises(ValidationError) as exc:
            order.ship(tracking_number="TRK-001")

        assert "Cannot ship an order in 'cancelled' status" in str(exc.value)

    def test_cancel_not_allowed_after_shipping(self, test_domain):
        order = Order(customer_id="cust-1", status=OrderStatus.SHIPPED.value)

        with pytest.raises(ValidationError) as exc:
            order.cancel(reason="Too late")

        assert "only draft or placed orders can be cancelled" in str(exc.value)


# --8<-- [end:tests]

domain.init(traverse=False)


@pytest.fixture
def test_domain():
    with domain.domain_context():
        yield domain
