"""The examples on the status transitions guide behave as the page says."""

import pytest

from protean.exceptions import ValidationError
from tests.docs.support import load_example

pytestmark = pytest.mark.no_test_domain


def _context(example):
    example.domain.init(traverse=False)
    with example.domain.domain_context():
        yield example


@pytest.fixture
def plain():
    yield from _context(
        load_example("guides/domain-behavior/status-transitions/001.py")
    )


@pytest.fixture
def lifecycle():
    yield from _context(
        load_example("guides/domain-behavior/status-transitions/002.py")
    )


@pytest.fixture
def idempotent():
    yield from _context(
        load_example("guides/domain-behavior/status-transitions/003.py")
    )


@pytest.fixture
def es_orders():
    yield from _context(
        load_example("guides/domain-behavior/status-transitions/004.py")
    )


@pytest.fixture
def two_statuses():
    yield from _context(
        load_example("guides/domain-behavior/status-transitions/005.py")
    )


def test_without_transitions_any_listed_value_is_accepted(plain):
    order = plain.Order()
    order.status = "DELIVERED"
    order.status = "DRAFT"

    assert order.status == "DRAFT"


def test_without_transitions_an_unlisted_value_is_rejected(plain):
    order = plain.Order()

    with pytest.raises(ValidationError) as exc:
        order.status = "LOST"

    assert list(exc.value.messages) == ["status"]
    assert order.status == "DRAFT"


def test_a_transition_outside_the_map_is_rejected(lifecycle):
    with pytest.raises(ValidationError) as exc:
        lifecycle.place_then_ship()

    assert exc.value.messages == {
        "status": [
            (
                "Invalid status transition from 'PLACED' to 'SHIPPED'. "
                "Allowed transitions: CONFIRMED, CANCELLED"
            )
        ]
    }


def test_leaving_a_terminal_state_is_rejected(lifecycle):
    order = lifecycle.Order(status="DELIVERED")

    with pytest.raises(ValidationError) as exc:
        order.status = "SHIPPED"

    assert exc.value.messages == {
        "status": [
            (
                "Invalid status transition from 'DELIVERED'. "
                "'DELIVERED' is a terminal state with no allowed transitions"
            )
        ]
    }


def test_re_entry_is_rejected_by_default(lifecycle):
    with pytest.raises(ValidationError) as exc:
        lifecycle.reenter_draft()

    assert exc.value.messages == {
        "status": [
            (
                "Re-entry into 'DRAFT' is not allowed. If this operation should be "
                "idempotent, add 'DRAFT' to its own target list in transitions"
            )
        ]
    }


def test_a_state_listed_in_its_own_targets_allows_re_entry(idempotent):
    order = idempotent.Order()
    order.status = "CANCELLED"

    order.status = "CANCELLED"

    assert order.status == "CANCELLED"


def test_the_initial_value_skips_the_transition_map(lifecycle):
    draft, placed = lifecycle.create_orders()

    assert (draft.status, placed.status) == ("DRAFT", "PLACED")


def test_atomic_change_checks_the_start_and_end_states(lifecycle):
    order = lifecycle.place_with_amount()

    assert (order.status, order.amount) == ("PLACED", 100.0)


def test_atomic_change_rejects_an_invalid_overall_move_and_rolls_back(lifecycle):
    order = lifecycle.Order()

    with pytest.raises(ValidationError) as exc:
        lifecycle.place_and_confirm(order)

    assert exc.value.messages == {
        "status": [
            (
                "Invalid status transition from 'DRAFT' to 'CONFIRMED'. "
                "Allowed transitions: PLACED, CANCELLED"
            )
        ]
    }
    assert order.status == "DRAFT"


def test_can_transition_to_reports_without_changing_state(lifecycle, capsys):
    order = lifecycle.Order()

    lifecycle.show_moves(order)

    assert capsys.readouterr().out.splitlines() == ["False", "True"]
    assert order.status == "DRAFT"


def test_raise_applies_a_valid_transition(es_orders):
    order = es_orders.Order()

    order.place()

    assert order.status == "PLACED"
    assert [type(event) for event in order._events] == [es_orders.OrderPlaced]


def test_raise_rejects_an_invalid_transition_and_drops_the_event(es_orders):
    order = es_orders.Order(status="CONFIRMED")

    with pytest.raises(ValidationError) as exc:
        order.place()

    assert exc.value.messages == {
        "status": [
            (
                "Invalid status transition from 'CONFIRMED'. "
                "'CONFIRMED' is a terminal state with no allowed transitions"
            )
        ]
    }
    assert order.status == "CONFIRMED"
    assert order._events == []


def test_each_status_field_checks_its_own_map(two_statuses):
    order = two_statuses.Order()
    order.payment = "PAID"

    with pytest.raises(ValidationError) as exc:
        order.fulfillment = "RETURNED"

    assert exc.value.messages == {
        "fulfillment": [
            (
                "Invalid status transition from 'UNFULFILLED' to 'RETURNED'. "
                "Allowed transitions: FULFILLED"
            )
        ]
    }
    assert (order.payment, order.fulfillment) == ("PAID", "UNFULFILLED")
