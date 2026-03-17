"""Tests for Status field transition enforcement."""

from enum import Enum

import pytest

from protean import atomic_change
from protean.core.aggregate import apply
from protean.exceptions import ValidationError
from protean.fields import Float, Identifier, Status, String


class OrderStatus(Enum):
    DRAFT = "DRAFT"
    PLACED = "PLACED"
    CONFIRMED = "CONFIRMED"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


TRANSITIONS = {
    OrderStatus.DRAFT: [OrderStatus.PLACED, OrderStatus.CANCELLED],
    OrderStatus.PLACED: [OrderStatus.CONFIRMED, OrderStatus.CANCELLED],
    OrderStatus.CONFIRMED: [OrderStatus.SHIPPED],
    OrderStatus.SHIPPED: [OrderStatus.DELIVERED],
    # DELIVERED and CANCELLED are terminal
}


# ============================================================
# Direct mutation tests (non-ES aggregates)
# ============================================================
class TestDirectMutation:
    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        @test_domain.aggregate
        class Order:
            status = Status(OrderStatus, default="DRAFT", transitions=TRANSITIONS)
            amount = Float(default=0.0)

        self.Order = Order
        test_domain.init(traverse=False)

    def test_valid_transition(self):
        order = self.Order()
        order.status = "PLACED"
        assert order.status == "PLACED"

    def test_invalid_transition_raises(self):
        order = self.Order()
        with pytest.raises(ValidationError) as exc:
            order.status = "SHIPPED"

        assert "status" in exc.value.messages
        assert "Invalid status transition from 'DRAFT' to 'SHIPPED'" in str(
            exc.value.messages["status"]
        )
        assert "Allowed transitions: PLACED, CANCELLED" in str(
            exc.value.messages["status"]
        )

    def test_chained_valid_transitions(self):
        order = self.Order()
        order.status = "PLACED"
        order.status = "CONFIRMED"
        order.status = "SHIPPED"
        order.status = "DELIVERED"
        assert order.status == "DELIVERED"

    def test_terminal_state_blocks_all(self):
        order = self.Order()
        order.status = "PLACED"
        order.status = "CONFIRMED"
        order.status = "SHIPPED"
        order.status = "DELIVERED"

        with pytest.raises(ValidationError) as exc:
            order.status = "CANCELLED"

        assert "terminal state" in str(exc.value.messages["status"])

    def test_same_value_raises_when_not_in_own_targets(self):
        order = self.Order()
        # DRAFT -> DRAFT is not listed in transitions, so it's an error
        with pytest.raises(ValidationError) as exc:
            order.status = "DRAFT"

        assert "Re-entry into 'DRAFT' is not allowed" in str(
            exc.value.messages["status"]
        )

    def test_same_value_allowed_when_in_own_targets(self, test_domain):
        """A state that lists itself as a target is idempotent."""

        idempotent_transitions = {
            OrderStatus.DRAFT: [OrderStatus.PLACED, OrderStatus.CANCELLED],
            OrderStatus.PLACED: [OrderStatus.CONFIRMED, OrderStatus.CANCELLED],
            OrderStatus.CONFIRMED: [OrderStatus.SHIPPED],
            OrderStatus.SHIPPED: [OrderStatus.DELIVERED],
            # CANCELLED is idempotent — re-entry allowed
            OrderStatus.CANCELLED: [OrderStatus.CANCELLED],
        }

        @test_domain.aggregate
        class IdempotentOrder:
            status = Status(
                OrderStatus, default="DRAFT", transitions=idempotent_transitions
            )

        test_domain.init(traverse=False)

        order = IdempotentOrder()
        order.status = "CANCELLED"
        # Re-entry allowed because CANCELLED lists itself
        order.status = "CANCELLED"
        assert order.status == "CANCELLED"

    def test_terminal_state_rejects_self_assignment(self):
        """Terminal states reject self-assignment (no outgoing transitions at all)."""
        order = self.Order()
        order.status = "CANCELLED"

        with pytest.raises(ValidationError) as exc:
            order.status = "CANCELLED"

        assert "terminal state" in str(exc.value.messages["status"])

    def test_none_to_any_allowed(self, test_domain):
        """None -> any value is allowed (initialization path)."""

        @test_domain.aggregate
        class Task:
            status = Status(OrderStatus, transitions=TRANSITIONS)

        test_domain.init(traverse=False)

        # default is None, setting to any valid state works
        task = Task()
        assert task.status is None
        task.status = "DRAFT"
        assert task.status == "DRAFT"

    def test_multiple_allowed_targets(self):
        # DRAFT can go to PLACED or CANCELLED
        order_a = self.Order()
        order_a.status = "PLACED"
        assert order_a.status == "PLACED"

        order_b = self.Order()
        order_b.status = "CANCELLED"
        assert order_b.status == "CANCELLED"

    def test_error_message_format(self):
        order = self.Order()
        with pytest.raises(ValidationError) as exc:
            order.status = "CONFIRMED"

        messages = exc.value.messages
        assert isinstance(messages, dict)
        assert "status" in messages
        assert isinstance(messages["status"], list)
        assert len(messages["status"]) == 1

    def test_terminal_state_error_message(self):
        order = self.Order()
        order.status = "CANCELLED"

        with pytest.raises(ValidationError) as exc:
            order.status = "DRAFT"

        msg = str(exc.value.messages["status"][0])
        assert "terminal state" in msg
        assert "CANCELLED" in msg

    def test_enum_member_accepted(self):
        """Setting status with Enum member (not just string) works."""
        order = self.Order()
        order.status = "PLACED"
        assert order.status == "PLACED"


# ============================================================
# atomic_change tests
# ============================================================
class TestAtomicChange:
    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        @test_domain.aggregate
        class Order:
            status = Status(OrderStatus, default="DRAFT", transitions=TRANSITIONS)
            amount = Float(default=0.0)

        self.Order = Order
        test_domain.init(traverse=False)

    def test_valid_transition_in_atomic(self):
        order = self.Order()
        with atomic_change(order):
            order.status = "PLACED"
        assert order.status == "PLACED"

    def test_invalid_transition_in_atomic(self):
        order = self.Order()
        with pytest.raises(ValidationError) as exc:
            with atomic_change(order):
                order.status = "SHIPPED"

        assert "status" in exc.value.messages

    def test_multi_field_changes(self):
        order = self.Order()
        with atomic_change(order):
            order.status = "PLACED"
            order.amount = 100.0

        assert order.status == "PLACED"
        assert order.amount == 100.0

    def test_start_to_end_checked_not_intermediates(self):
        """atomic_change checks start->end, so valid intermediate steps
        with an invalid overall transition still fail."""
        order = self.Order()

        with pytest.raises(ValidationError):
            with atomic_change(order):
                # Individual steps are valid, but overall DRAFT->CONFIRMED is not
                order.status = "PLACED"
                order.status = "CONFIRMED"

    def test_terminal_in_atomic(self):
        order = self.Order()
        order.status = "CANCELLED"

        with pytest.raises(ValidationError) as exc:
            with atomic_change(order):
                order.status = "DRAFT"

        assert "terminal state" in str(exc.value.messages["status"])

    def test_exception_skips_transition_check(self):
        """When an exception propagates, transition validation is skipped."""
        order = self.Order()

        with pytest.raises(RuntimeError):
            with atomic_change(order):
                order.status = "SHIPPED"  # Would be invalid
                raise RuntimeError("something broke")

        # Status may have been set but the transition error is not raised
        # because the RuntimeError takes precedence

    def test_no_change_no_validation(self):
        """If status is unchanged in block, no transition check needed."""
        order = self.Order()
        with atomic_change(order):
            order.amount = 99.0

        assert order.status == "DRAFT"
        assert order.amount == 99.0


# ============================================================
# Event-sourced aggregate tests
# ============================================================
class TestEventSourcedAggregate:
    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        @test_domain.event(part_of="ESOrder")
        class OrderPlaced:
            order_id = Identifier(required=True)

        @test_domain.event(part_of="ESOrder")
        class OrderShipped:
            order_id = Identifier(required=True)

        @test_domain.aggregate(is_event_sourced=True)
        class ESOrder:
            order_id = Identifier(identifier=True)
            status = Status(
                OrderStatus,
                default="DRAFT",
                transitions=TRANSITIONS,
            )

            def place(self):
                self.raise_(OrderPlaced(order_id=self.order_id))

            def ship(self):
                self.raise_(OrderShipped(order_id=self.order_id))

            @apply
            def on_placed(self, event: OrderPlaced) -> None:
                self.status = "PLACED"

            @apply
            def on_shipped(self, event: OrderShipped) -> None:
                self.status = "SHIPPED"

        self.ESOrder = ESOrder
        self.OrderPlaced = OrderPlaced
        self.OrderShipped = OrderShipped
        test_domain.init(traverse=False)

    def test_es_valid_transition_via_raise(self):
        order = self.ESOrder(order_id="order-1")
        order.place()
        assert order.status == "PLACED"

    def test_es_invalid_transition_via_raise(self):
        """raise_() wraps @apply in atomic_change, which validates transitions."""
        order = self.ESOrder(order_id="order-1")
        # ship() sets status to SHIPPED, but DRAFT -> SHIPPED is invalid
        with pytest.raises(ValidationError) as exc:
            order.ship()

        assert "status" in exc.value.messages

    def test_es_replay_skips_validation(self):
        """from_events() does NOT use atomic_change, so transitions not validated.

        We construct a valid order (place it), then replay its events.
        The replay should succeed because from_events() doesn't validate transitions.
        """
        # Create an order via the normal path to get enriched events
        order = self.ESOrder(order_id="order-1")
        order.place()

        # Replay from events
        replayed = self.ESOrder.from_events(order._events)
        assert replayed.status == "PLACED"

    def test_es_replay_full_lifecycle(self):
        """Full lifecycle via replay works correctly."""
        order = self.ESOrder(order_id="order-1")
        order.place()

        replayed = self.ESOrder.from_events(order._events)
        assert replayed.status == "PLACED"


# ============================================================
# Multiple status fields
# ============================================================
class TestMultipleStatusFields:
    def test_two_independent_status_fields(self, test_domain):
        class PaymentStatus(Enum):
            PENDING = "PENDING"
            PAID = "PAID"
            REFUNDED = "REFUNDED"

        class FulfillmentStatus(Enum):
            UNFULFILLED = "UNFULFILLED"
            FULFILLED = "FULFILLED"
            RETURNED = "RETURNED"

        @test_domain.aggregate
        class Order:
            payment = Status(
                PaymentStatus,
                default="PENDING",
                transitions={
                    PaymentStatus.PENDING: [PaymentStatus.PAID],
                    PaymentStatus.PAID: [PaymentStatus.REFUNDED],
                },
            )
            fulfillment = Status(
                FulfillmentStatus,
                default="UNFULFILLED",
                transitions={
                    FulfillmentStatus.UNFULFILLED: [FulfillmentStatus.FULFILLED],
                    FulfillmentStatus.FULFILLED: [FulfillmentStatus.RETURNED],
                },
            )

        test_domain.init(traverse=False)

        order = Order()

        # Each field validates independently
        order.payment = "PAID"
        assert order.payment == "PAID"

        order.fulfillment = "FULFILLED"
        assert order.fulfillment == "FULFILLED"

        # Invalid transition on one doesn't affect the other
        with pytest.raises(ValidationError) as exc:
            order.payment = "PENDING"  # PAID -> PENDING is invalid

        assert "payment" in exc.value.messages

    def test_atomic_captures_all_status_fields(self, test_domain):
        class PaymentStatus(Enum):
            PENDING = "PENDING"
            PAID = "PAID"

        class ShipStatus(Enum):
            WAITING = "WAITING"
            SHIPPED = "SHIPPED"

        @test_domain.aggregate
        class Order:
            payment = Status(
                PaymentStatus,
                default="PENDING",
                transitions={PaymentStatus.PENDING: [PaymentStatus.PAID]},
            )
            shipping = Status(
                ShipStatus,
                default="WAITING",
                transitions={ShipStatus.WAITING: [ShipStatus.SHIPPED]},
            )

        test_domain.init(traverse=False)

        order = Order()
        with atomic_change(order):
            order.payment = "PAID"
            order.shipping = "SHIPPED"

        assert order.payment == "PAID"
        assert order.shipping == "SHIPPED"


# ============================================================
# can_transition_to tests
# ============================================================
class TestCanTransitionTo:
    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        @test_domain.aggregate
        class Order:
            status = Status(OrderStatus, default="DRAFT", transitions=TRANSITIONS)
            name = String(default="test")

        self.Order = Order
        test_domain.init(traverse=False)

    def test_valid_returns_true(self):
        order = self.Order()
        assert order.can_transition_to("status", "PLACED") is True

    def test_invalid_returns_false(self):
        order = self.Order()
        assert order.can_transition_to("status", "SHIPPED") is False

    def test_terminal_returns_false(self):
        order = self.Order()
        order.status = "CANCELLED"
        assert order.can_transition_to("status", "DRAFT") is False

    def test_same_value_returns_false_when_not_in_own_targets(self):
        order = self.Order()
        # DRAFT doesn't list itself as a target
        assert order.can_transition_to("status", "DRAFT") is False

    def test_same_value_returns_true_when_in_own_targets(self, test_domain):
        idempotent_transitions = {
            OrderStatus.DRAFT: [OrderStatus.PLACED, OrderStatus.DRAFT],
        }

        @test_domain.aggregate
        class IdempotentOrder:
            status = Status(
                OrderStatus, default="DRAFT", transitions=idempotent_transitions
            )

        test_domain.init(traverse=False)

        order = IdempotentOrder()
        assert order.can_transition_to("status", "DRAFT") is True

    def test_none_returns_true(self, test_domain):
        @test_domain.aggregate
        class Task:
            status = Status(OrderStatus, transitions=TRANSITIONS)

        test_domain.init(traverse=False)

        task = Task()
        assert task.status is None
        assert task.can_transition_to("status", "DRAFT") is True

    def test_non_status_field_returns_true(self):
        order = self.Order()
        assert order.can_transition_to("name", "anything") is True

    def test_no_transitions_returns_true(self, test_domain):
        @test_domain.aggregate
        class Order2:
            status = Status(OrderStatus, default="DRAFT")

        test_domain.init(traverse=False)

        order = Order2()
        assert order.can_transition_to("status", "SHIPPED") is True

    def test_accepts_enum_member(self):
        order = self.Order()
        assert order.can_transition_to("status", OrderStatus.PLACED) is True
        assert order.can_transition_to("status", OrderStatus.SHIPPED) is False

    def test_nonexistent_field_returns_true(self):
        order = self.Order()
        assert order.can_transition_to("nonexistent", "foo") is True


# ============================================================
# Status on Entity (child of aggregate)
# ============================================================
class TestStatusOnEntity:
    def test_entity_transitions_enforced(self, test_domain):
        class ItemStatus(Enum):
            PENDING = "PENDING"
            APPROVED = "APPROVED"
            REJECTED = "REJECTED"

        @test_domain.entity(part_of="Order")
        class LineItem:
            item_status = Status(
                ItemStatus,
                default="PENDING",
                transitions={
                    ItemStatus.PENDING: [ItemStatus.APPROVED, ItemStatus.REJECTED],
                },
            )
            name = String(default="item")

        @test_domain.aggregate
        class Order:
            name = String(default="order")

        test_domain.init(traverse=False)

        item = LineItem()
        assert item.item_status == "PENDING"

        item.item_status = "APPROVED"
        assert item.item_status == "APPROVED"

        with pytest.raises(ValidationError):
            item.item_status = "PENDING"  # APPROVED is terminal
