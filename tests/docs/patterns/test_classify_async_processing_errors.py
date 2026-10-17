"""Run the examples on ``docs/patterns/classify-async-processing-errors.md``."""

import logging

import pytest

from protean import Engine
from protean.utils.eventing import Message
from tests.docs.support import load_example

pytestmark = pytest.mark.no_test_domain

HOOKS = ("on_transient_error", "on_data_error", "on_logic_error")


@pytest.fixture
def example():
    module = load_example("patterns/classify-async-processing-errors/001.py")
    module.domain.init(traverse=False)
    with module.domain.domain_context():
        yield module


@pytest.fixture
def with_mixin():
    module = load_example("patterns/classify-async-processing-errors/002.py")
    module.domain.init(traverse=False)
    with module.domain.domain_context():
        yield module


def _recording_handler(mixin):
    class RecordingHandler(mixin):
        calls = []

        @classmethod
        def on_transient_error(cls, exc, message):
            cls.calls.append(("on_transient_error", exc, message))

        @classmethod
        def on_data_error(cls, exc, message):
            cls.calls.append(("on_data_error", exc, message))

        @classmethod
        def on_logic_error(cls, exc, message):
            cls.calls.append(("on_logic_error", exc, message))

    return RecordingHandler


def _hook_reached(example, exc):
    handler = _recording_handler(example.ErrorClassificationMixin)
    message = object()
    handler.handle_error(exc, message)
    assert len(handler.calls) == 1
    hook, seen_exc, seen_message = handler.calls[0]
    assert seen_exc is exc
    assert seen_message is message
    return hook


@pytest.mark.parametrize(
    ("exc", "hook"),
    [
        (ConnectionError("refused"), "on_transient_error"),
        (KeyError("currency"), "on_data_error"),
        (ZeroDivisionError("division by zero"), "on_logic_error"),
    ],
)
def test_mixin_routes_each_kind_to_one_hook(example, exc, hook):
    assert _hook_reached(example, exc) == hook


def test_transient_check_runs_before_the_data_check(example):
    # A ValueError is a data error type, but its message names a deadlock.
    assert _hook_reached(example, ValueError("deadlock detected")) == (
        "on_transient_error"
    )


def test_a_plain_value_error_is_a_data_error(example):
    assert _hook_reached(example, ValueError("bad amount")) == "on_data_error"


def test_a_message_pattern_marks_a_logic_type_as_transient(example):
    assert _hook_reached(example, RuntimeError("Lock timeout exceeded")) == (
        "on_transient_error"
    )


def test_extra_transient_types_extend_the_transient_list(example):
    class GatewayTimeout(Exception):
        pass

    handler = _recording_handler(example.ErrorClassificationMixin)
    handler.handle_error(GatewayTimeout(), None)
    assert [call[0] for call in handler.calls] == ["on_logic_error"]

    class WithExtra(handler):
        _extra_transient_types = (GatewayTimeout,)
        calls = []

    WithExtra.handle_error(GatewayTimeout(), None)
    assert [call[0] for call in WithExtra.calls] == ["on_transient_error"]


@pytest.mark.parametrize(
    ("members", "hook"),
    [
        ((ConnectionError("a"), TimeoutError("b")), "on_transient_error"),
        ((ConnectionError("a"), KeyError("b")), "on_data_error"),
        ((ConnectionError("a"), ZeroDivisionError("b")), "on_logic_error"),
    ],
)
def test_mixin_classifies_an_exception_group_by_its_members(example, members, hook):
    group = ExceptionGroup("two handler methods failed", list(members))
    assert _hook_reached(example, group) == hook


def _message_for(example):
    event = example.OrderPlaced(
        order_id="o1", customer_id="c1", customer_name="Ada", items=[], total=10.0
    )
    return Message.from_domain_object(event)


@pytest.mark.parametrize(
    ("handler_name", "exc", "alert"),
    [
        ("InventoryEventHandler", ConnectionError("refused"), None),
        ("InventoryEventHandler", KeyError("product_id"), "data"),
        ("InventoryEventHandler", ZeroDivisionError("division by zero"), "logic"),
        ("ShippingEventHandler", TimeoutError("slow"), None),
        ("ShippingEventHandler", KeyError("customer_id"), "data"),
        ("ShippingEventHandler", ZeroDivisionError("division by zero"), "logic"),
        ("OrderDashboardProjector", ConnectionError("refused"), None),
        ("OrderDashboardProjector", KeyError("currency"), "stale"),
        ("OrderDashboardProjector", ZeroDivisionError("division by zero"), "stale"),
    ],
)
def test_inline_handle_error_alerts_by_kind(example, handler_name, exc, alert):
    example.alerts.clear()
    handler = getattr(example, handler_name)
    handler.handle_error(exc, _message_for(example))
    expected = [] if alert is None else [(alert, handler_name, exc)]
    assert example.alerts == expected


def test_handler_with_mixin_pages_on_a_logic_error_only(with_mixin):
    handler = with_mixin.InventoryEventHandler
    with_mixin.pagerduty.incidents.clear()

    handler.handle_error(ConnectionError("refused"), None)
    handler.handle_error(KeyError("product_id"), None)
    assert with_mixin.pagerduty.incidents == []

    handler.handle_error(ZeroDivisionError("division by zero"), None)
    assert with_mixin.pagerduty.incidents == [
        {
            "summary": "Logic error in InventoryEventHandler: division by zero",
            "severity": "critical",
        }
    ]


def test_projector_mixin_alerts_on_every_non_transient_error(with_mixin):
    projector = with_mixin.OrderDashboardProjector
    data_error, logic_error = KeyError("currency"), ZeroDivisionError("bug")
    with_mixin.stale_projection_alerts.clear()

    projector.handle_error(ConnectionError("refused"), None)
    assert with_mixin.stale_projection_alerts == []

    projector.handle_error(data_error, None)
    projector.handle_error(logic_error, None)
    assert with_mixin.stale_projection_alerts == [
        ("OrderDashboardProjector", data_error),
        ("OrderDashboardProjector", logic_error),
    ]


def test_subscriber_with_mixin_classifies_a_dict_payload_failure(with_mixin, caplog):
    subscriber = with_mixin.PaymentCompletedSubscriber
    with caplog.at_level(logging.WARNING):
        subscriber.handle_error(ConnectionError("refused"), {"order_id": "o1"})
        subscriber.handle_error(KeyError("amount"), {"order_id": "o1"})

    records = [(r.levelno, r.getMessage()) for r in caplog.records]
    assert records == [
        (logging.WARNING, "Transient error in PaymentCompletedSubscriber: refused"),
        (logging.ERROR, "Data error in PaymentCompletedSubscriber: 'amount'"),
    ]


def _place_order(with_mixin, product_id):
    order = with_mixin.Order(
        customer_id="c1",
        customer_name="Ada",
        items=[{"product_id": product_id, "quantity": 2}],
        total=20.0,
    )
    order.place()
    with_mixin.domain.repository_for(with_mixin.Order).add(order)
    return order


def test_engine_calls_the_mixin_when_a_handler_fails(with_mixin):
    with_mixin.pagerduty.incidents.clear()
    _place_order(with_mixin, "missing-product")

    Engine(with_mixin.domain, test_mode=True).run()

    # The subscription retries the failed message and the engine calls
    # handle_error after each attempt, so every incident is the same one.
    incidents = with_mixin.pagerduty.incidents
    assert incidents
    summary = (
        "Logic error in InventoryEventHandler: `Inventory` object with "
        "identifier missing-product does not exist."
    )
    assert all(
        incident == {"summary": summary, "severity": "critical"}
        for incident in incidents
    )


def test_engine_does_not_page_when_the_handler_succeeds(with_mixin):
    with_mixin.pagerduty.incidents.clear()
    with_mixin.domain.repository_for(with_mixin.Inventory).add(
        with_mixin.Inventory(product_id="p1", on_hand=5)
    )
    order = _place_order(with_mixin, "p1")

    Engine(with_mixin.domain, test_mode=True).run()

    assert with_mixin.pagerduty.incidents == []
    inventory = with_mixin.domain.repository_for(with_mixin.Inventory).get("p1")
    assert (inventory.on_hand, inventory.reserved) == (3, 2)
    dashboard = with_mixin.domain.view_for(with_mixin.OrderDashboard).get(order.id)
    assert dashboard.status == "placed"


@pytest.mark.parametrize(
    ("members", "transient", "data_error"),
    [
        ((ConnectionError("a"), TimeoutError("b")), True, False),
        ((ConnectionError("a"), KeyError("b")), False, True),
        ((ConnectionError("a"), ZeroDivisionError("b")), False, False),
    ],
)
def test_classifier_functions_recurse_into_an_exception_group(
    example, members, transient, data_error
):
    group = ExceptionGroup("two handler methods failed", list(members))
    assert example._is_transient(group) is transient
    assert example._is_data_error(group) is data_error
