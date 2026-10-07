"""Run the examples on ``docs/patterns/aggregate-state-machines.md``."""

import re
import subprocess
import sys

import pytest

from protean.exceptions import ValidationError
from tests.docs.support import DOCS_SRC, REPO_ROOT, load_example

pytestmark = pytest.mark.no_test_domain

# Every transition method on the Order aggregate, with the arguments it takes.
METHODS = {
    "place": {},
    "pay": {},
    "ship": {"tracking_number": "TRK-1"},
    "deliver": {},
    "cancel": {"reason": "changed mind"},
    "refund": {},
}

# The transition map the page shows. ``test_transition_map_matches_the_page``
# checks that the example's map is this one, so the cases below follow the page.
TRANSITIONS = {
    "draft": {"place": "placed", "cancel": "cancelled"},
    "placed": {"pay": "paid", "cancel": "cancelled"},
    "paid": {"ship": "shipped", "refund": "refunded"},
    "shipped": {"deliver": "delivered"},
    "delivered": {},
    "cancelled": {},
    "refunded": {},
}

ALLOWED = [
    (source, method, target)
    for source, moves in TRANSITIONS.items()
    for method, target in moves.items()
]
FORBIDDEN = [
    (source, method)
    for source, moves in TRANSITIONS.items()
    for method in METHODS
    if method not in moves
]

# The event each transition raises; ``deliver`` raises none.
EVENTS = {
    "place": "OrderPlaced",
    "pay": "OrderPaid",
    "ship": "OrderShipped",
    "cancel": "OrderCancelled",
    "refund": "OrderRefunded",
}


@pytest.fixture
def example():
    module = load_example("patterns/aggregate-state-machines/001.py")
    with module.domain.domain_context():
        yield module


def test_transition_map_matches_the_page():
    example = load_example("patterns/aggregate-state-machines/002.py")

    assert example.Order.TRANSITIONS == TRANSITIONS


def test_transition_map_names_every_state_and_method(example):
    assert set(TRANSITIONS) == {status.value for status in example.OrderStatus}
    assert {m for moves in TRANSITIONS.values() for m in moves} == set(METHODS)


@pytest.mark.parametrize(("source", "method", "target"), ALLOWED)
def test_allowed_transition_changes_the_state(example, source, method, target):
    order = example.Order(customer_id="cust-1", total=25.0, status=source)

    getattr(order, method)(**METHODS[method])

    assert order.status == target
    if method in EVENTS:
        assert [type(event).__name__ for event in order._events] == [EVENTS[method]]
        assert order._events[0].order_id == order.order_id
    else:
        assert order._events == []


@pytest.mark.parametrize(("source", "method"), FORBIDDEN)
def test_forbidden_transition_raises_and_keeps_the_state(example, source, method):
    order = example.Order(customer_id="cust-1", total=25.0, status=source)

    with pytest.raises(ValidationError) as exc:
        getattr(order, method)(**METHODS[method])

    message = exc.value.messages["status"][0]
    assert message.startswith(f"Cannot {method} an order in '{source}' status")
    assert order.status == source
    assert order._events == []


def test_cancel_error_names_the_states_that_allow_it(example):
    order = example.Order(customer_id="cust-1", status="shipped")

    with pytest.raises(ValidationError) as exc:
        order.cancel(reason="Too late")

    assert exc.value.messages["status"] == [
        (
            "Cannot cancel an order in 'shipped' status; "
            "only draft or placed orders can be cancelled"
        )
    ]


def test_transitions_record_their_data(example):
    order = example.Order(customer_id="cust-1", total=40.0, status="paid")

    order.ship(tracking_number="TRK-9")

    assert order.tracking_number == "TRK-9"
    assert order.shipped_at is not None
    assert order._events[0].tracking_number == "TRK-9"

    refunded = example.Order(customer_id="cust-1", total=40.0, status="paid")
    refunded.refund()
    assert refunded._events[0].refund_amount == 40.0
    assert refunded.refunded_at is not None


def test_status_outside_the_enum_is_rejected(example):
    with pytest.raises(ValidationError) as exc:
        example.Order(customer_id="cust-1", status="shiped")

    assert "status" in exc.value.messages


def test_handlers_load_call_and_save(example):
    domain = example.domain
    repo = domain.repository_for(example.Order)
    order = example.Order(customer_id="cust-1", total=10.0)
    repo.add(order)

    domain.process(example.PlaceOrder(order_id=order.order_id), asynchronous=False)
    assert repo.get(order.order_id).status == "placed"

    domain.process(
        example.CancelOrder(order_id=order.order_id, reason="no longer needed"),
        asynchronous=False,
    )
    cancelled = repo.get(order.order_id)
    assert cancelled.status == "cancelled"
    assert cancelled.cancellation_reason == "no longer needed"

    # The aggregate refuses the transition, so the handler saves nothing
    with pytest.raises(ValidationError):
        domain.process(
            example.ShipOrder(order_id=order.order_id, tracking_number="TRK-1"),
            asynchronous=False,
        )
    assert repo.get(order.order_id).status == "cancelled"


def test_ship_order_handler_saves_the_shipped_order(example):
    domain = example.domain
    repo = domain.repository_for(example.Order)
    order = example.Order(customer_id="cust-1", total=10.0, status="paid")
    repo.add(order)

    domain.process(
        example.ShipOrder(order_id=order.order_id, tracking_number="TRK-7"),
        asynchronous=False,
    )

    shipped = repo.get(order.order_id)
    assert shipped.status == "shipped"
    assert shipped.tracking_number == "TRK-7"
    assert shipped.shipped_at is not None


def test_deliver_records_the_delivery_time(example):
    order = example.Order(customer_id="cust-1", status="shipped")
    assert order.delivered_at is None

    order.deliver()

    assert order.status == "delivered"
    assert order.delivered_at is not None


def test_page_tests_pass_under_pytest():
    # Run the tests the page shows the way a reader would: as a pytest module.
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            str(DOCS_SRC / "patterns/aggregate-state-machines/001.py"),
            "-p",
            "no:cacheprovider",
            "-p",
            "no:randomly",
            "-q",
            "--import-mode=importlib",
            "-W",
            "error::pytest.PytestCollectionWarning",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert re.search(r"\b5 passed\b", result.stdout), result.stdout


@pytest.fixture
def guarded():
    module = load_example("patterns/aggregate-state-machines/003.py")
    with module.domain.domain_context():
        yield module


@pytest.mark.parametrize("terminal", ["delivered", "cancelled", "refunded"])
def test_terminal_order_cannot_be_modified(guarded, terminal):
    order = guarded.Order(customer_id="cust-1", status=terminal)

    with pytest.raises(ValidationError) as exc:
        order.tracking_number = "TRK-1"

    assert exc.value.messages["status"] == [
        f"Order in '{terminal}' status cannot be modified"
    ]
    assert order.tracking_number is None


def test_order_can_move_into_a_terminal_state(guarded):
    order = guarded.Order(customer_id="cust-1", status="placed")

    order.status = "cancelled"

    assert order.status == "cancelled"


def test_shipped_order_needs_tracking_number_and_timestamp(guarded):
    order = guarded.Order(customer_id="cust-1", status="paid")

    with pytest.raises(ValidationError) as exc:
        order.status = "shipped"

    assert exc.value.messages == {
        "tracking_number": ["Shipped orders must have a tracking number"],
        "shipped_at": ["Shipped orders must have a shipped_at timestamp"],
    }


def test_shipped_order_with_its_data_is_valid(guarded):
    order = guarded.Order(
        customer_id="cust-1",
        status="shipped",
        tracking_number="TRK-1",
        shipped_at="2026-01-01T00:00:00+00:00",
    )

    assert order.status == "shipped"
