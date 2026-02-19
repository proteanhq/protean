"""Tests for the EventLog collection class.

EventLog is a pure Python wrapper around a list of events with Pythonic
access patterns: ``in``, ``[]``, ``len``, iteration, ``.get()``,
``.of_type()``, and ``.types``.
"""

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.fields import Float, Identifier, String
from protean.testing import EventLog


# ---------------------------------------------------------------------------
# Domain elements needed to instantiate events
# ---------------------------------------------------------------------------
class Shipment(BaseAggregate):
    shipment_id = Identifier(identifier=True)
    customer = String()


class OrderPlaced(BaseEvent):
    order_id = Identifier()
    customer = String()


class OrderConfirmed(BaseEvent):
    order_id = Identifier()


class PaymentReceived(BaseEvent):
    order_id = Identifier()
    amount = Float()


class OrderShipped(BaseEvent):
    order_id = Identifier()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Shipment)
    test_domain.register(OrderPlaced, part_of=Shipment)
    test_domain.register(OrderConfirmed, part_of=Shipment)
    test_domain.register(PaymentReceived, part_of=Shipment)
    test_domain.register(OrderShipped, part_of=Shipment)
    test_domain.init(traverse=False)


@pytest.fixture
def placed_event():
    return OrderPlaced(order_id="order-1", customer="Alice")


@pytest.fixture
def confirmed_event():
    return OrderConfirmed(order_id="order-1")


@pytest.fixture
def payment_event():
    return PaymentReceived(order_id="order-1", amount=99.99)


@pytest.fixture
def empty_log():
    return EventLog([])


@pytest.fixture
def single_log(placed_event):
    return EventLog([placed_event])


@pytest.fixture
def multi_log(placed_event, confirmed_event, payment_event):
    return EventLog([placed_event, confirmed_event, payment_event])


# ---------------------------------------------------------------------------
# Tests: Empty EventLog
# ---------------------------------------------------------------------------
class TestEmptyEventLog:
    def test_len_is_zero(self, empty_log):
        assert len(empty_log) == 0

    def test_contains_returns_false(self, empty_log):
        assert OrderPlaced not in empty_log

    def test_getitem_by_type_raises_key_error(self, empty_log):
        with pytest.raises(KeyError, match="OrderPlaced"):
            empty_log[OrderPlaced]

    def test_getitem_by_index_raises_index_error(self, empty_log):
        with pytest.raises(IndexError):
            empty_log[0]

    def test_get_returns_none(self, empty_log):
        assert empty_log.get(OrderPlaced) is None

    def test_get_returns_custom_default(self, empty_log):
        sentinel = object()
        assert empty_log.get(OrderPlaced, sentinel) is sentinel

    def test_of_type_returns_empty_list(self, empty_log):
        assert empty_log.of_type(OrderPlaced) == []

    def test_types_returns_empty_list(self, empty_log):
        assert empty_log.types == []

    def test_iteration_yields_nothing(self, empty_log):
        assert list(empty_log) == []

    def test_repr(self, empty_log):
        assert repr(empty_log) == "EventLog([])"


# ---------------------------------------------------------------------------
# Tests: Single-event EventLog
# ---------------------------------------------------------------------------
class TestSingleEventLog:
    def test_len_is_one(self, single_log):
        assert len(single_log) == 1

    def test_contains_matching_type(self, single_log):
        assert OrderPlaced in single_log

    def test_contains_non_matching_type(self, single_log):
        assert OrderConfirmed not in single_log

    def test_getitem_by_type(self, single_log, placed_event):
        assert single_log[OrderPlaced] is placed_event

    def test_getitem_by_index(self, single_log, placed_event):
        assert single_log[0] is placed_event

    def test_getitem_by_negative_index(self, single_log, placed_event):
        assert single_log[-1] is placed_event

    def test_get_returns_event(self, single_log, placed_event):
        assert single_log.get(OrderPlaced) is placed_event

    def test_get_returns_none_for_missing(self, single_log):
        assert single_log.get(OrderConfirmed) is None

    def test_of_type_returns_match(self, single_log, placed_event):
        assert single_log.of_type(OrderPlaced) == [placed_event]

    def test_of_type_returns_empty_for_mismatch(self, single_log):
        assert single_log.of_type(OrderConfirmed) == []

    def test_types(self, single_log):
        assert single_log.types == [OrderPlaced]

    def test_iteration(self, single_log, placed_event):
        assert list(single_log) == [placed_event]

    def test_repr(self, single_log):
        assert repr(single_log) == "EventLog(['OrderPlaced'])"


# ---------------------------------------------------------------------------
# Tests: Multi-event EventLog
# ---------------------------------------------------------------------------
class TestMultiEventLog:
    def test_len(self, multi_log):
        assert len(multi_log) == 3

    def test_contains_all_types(self, multi_log):
        assert OrderPlaced in multi_log
        assert OrderConfirmed in multi_log
        assert PaymentReceived in multi_log

    def test_contains_missing_type(self, multi_log):
        assert OrderShipped not in multi_log

    def test_getitem_by_type_returns_first_match(self, multi_log, placed_event):
        assert multi_log[OrderPlaced] is placed_event

    def test_getitem_by_index(
        self, multi_log, placed_event, confirmed_event, payment_event
    ):
        assert multi_log[0] is placed_event
        assert multi_log[1] is confirmed_event
        assert multi_log[2] is payment_event

    def test_getitem_by_type_raises_for_missing(self, multi_log):
        with pytest.raises(KeyError, match="OrderShipped"):
            multi_log[OrderShipped]

    def test_get_returns_first_match(self, multi_log, confirmed_event):
        assert multi_log.get(OrderConfirmed) is confirmed_event

    def test_of_type_returns_all_matches(self):
        """When multiple events of the same type exist, of_type returns all."""
        e1 = PaymentReceived(order_id="order-1", amount=50.0)
        e2 = PaymentReceived(order_id="order-1", amount=25.0)
        e3 = OrderPlaced(order_id="order-1", customer="Bob")
        log = EventLog([e1, e3, e2])

        payments = log.of_type(PaymentReceived)
        assert len(payments) == 2
        assert payments[0] is e1
        assert payments[1] is e2

    def test_types_preserves_order(self, multi_log):
        assert multi_log.types == [OrderPlaced, OrderConfirmed, PaymentReceived]

    def test_iteration_order(
        self, multi_log, placed_event, confirmed_event, payment_event
    ):
        events = list(multi_log)
        assert events == [placed_event, confirmed_event, payment_event]

    def test_repr(self, multi_log):
        assert (
            repr(multi_log)
            == "EventLog(['OrderPlaced', 'OrderConfirmed', 'PaymentReceived'])"
        )


# ---------------------------------------------------------------------------
# Tests: Event attribute access
# ---------------------------------------------------------------------------
class TestEventAttributeAccess:
    def test_access_event_fields_via_getitem(self):
        event = PaymentReceived(order_id="order-42", amount=123.45)
        log = EventLog([event])

        assert log[PaymentReceived].order_id == "order-42"
        assert log[PaymentReceived].amount == 123.45

    def test_access_event_fields_via_get(self):
        event = OrderPlaced(order_id="order-7", customer="Charlie")
        log = EventLog([event])

        assert log.get(OrderPlaced).customer == "Charlie"

    def test_access_event_fields_via_index(self):
        event = OrderPlaced(order_id="order-7", customer="Charlie")
        log = EventLog([event])

        assert log[0].customer == "Charlie"
