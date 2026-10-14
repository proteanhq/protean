"""Run the examples on ``docs/concepts/philosophy/always-valid.md``."""

from datetime import UTC, datetime, timedelta

import pytest

from protean.exceptions import ValidationError
from tests.docs.support import load_example

pytestmark = pytest.mark.no_test_domain


def _context(example):
    example.domain.init(traverse=False)
    return example.domain.domain_context()


# Layer 1: field constraints


def test_field_constraints_reject_each_bad_value(capsys):
    example = load_example("concepts/philosophy/always-valid/001.py")
    with _context(example):
        example.show_field_checks()
    assert capsys.readouterr().out.splitlines() == [
        "{'customer_id': ['is required']}",
        (
            "{'quantity': ['Input should be a valid integer, unable to parse string"
            " as an integer']}"
        ),
        "{'quantity': ['Input should be greater than or equal to 1']}",
        "{'unit_price': ['Input should be greater than or equal to 0.01']}",
    ]


def test_field_constraints_accept_valid_values():
    example = load_example("concepts/philosophy/always-valid/001.py")
    with _context(example):
        order = example.Order(customer_id="cust-1")
        item = example.OrderItem(product_name="Widget", quantity=1, unit_price=0.01)
        assert order.status == "draft"
        assert (item.quantity, item.unit_price) == (1, 0.01)


def test_rejected_assignment_leaves_the_old_value():
    example = load_example("concepts/philosophy/always-valid/001.py")
    with _context(example):
        item = example.OrderItem(product_name="Widget", quantity=1, unit_price=10.0)
        with pytest.raises(ValidationError) as exc:
            item.unit_price = -5.0
        assert set(exc.value.messages) == {"unit_price"}
        assert item.unit_price == 10.0


# Layer 2: value object invariants


def test_money_invariants_reject_bad_values(capsys):
    example = load_example("concepts/philosophy/always-valid/002.py")
    with _context(example):
        example.show_money_checks()
    assert capsys.readouterr().out.splitlines() == [
        "{'amount': ['Amount cannot be negative']}",
        "{'currency': ['Unrecognized currency: XYZ']}",
        "{'currency': ['String should have at most 3 characters']}",
    ]


def test_money_rejects_a_three_letter_currency_it_does_not_know():
    example = load_example("concepts/philosophy/always-valid/002.py")
    with _context(example):
        with pytest.raises(ValidationError) as exc:
            example.Money(amount=10, currency="ABC")
        assert exc.value.messages == {"currency": ["Unrecognized currency: ABC"]}


def test_order_accepts_a_valid_money_total():
    example = load_example("concepts/philosophy/always-valid/002.py")
    with _context(example):
        order = example.Order(customer_id="cust-1")
        order.total = example.Money(amount=50, currency="USD")
        assert (order.total.amount, order.total.currency) == (50.0, "USD")


# Layer 3: aggregate invariants


def test_aggregate_invariants_run_on_construction_and_assignment(capsys):
    example = load_example("concepts/philosophy/always-valid/003.py")
    with _context(example):
        order = example.show_invariant_checks()
        assert order.status == "confirmed"
        assert [item.product_name for item in order.items] == ["Widget"]
    assert capsys.readouterr().out.splitlines() == [
        "['Order must have at least one item']",
        "['Order must have at least one item']",
    ]


def test_rejected_status_change_leaves_the_order_a_draft():
    example = load_example("concepts/philosophy/always-valid/003.py")
    with _context(example):
        order = example.Order(customer_id="cust-1")
        with pytest.raises(ValidationError):
            order.status = "confirmed"
        assert order.status == "draft"


def test_total_must_match_the_items():
    example = load_example("concepts/philosophy/always-valid/003.py")
    with _context(example):
        with pytest.raises(ValidationError) as exc:
            example.Order(
                customer_id="cust-1",
                total=example.Money(amount=25.0, currency="USD"),
                items=[
                    example.OrderItem(
                        product_name="Widget", quantity=2, unit_price=10.0
                    )
                ],
            )
        assert exc.value.messages == {
            "total": ["Total 25.0 does not match items total 20.0"]
        }


def test_atomic_change_accepts_changes_that_are_valid_together():
    example = load_example("concepts/philosophy/always-valid/003.py")
    with _context(example):
        order = example.change_total_and_items()
        assert order.total.amount == 120.0
        assert sorted(item.product_name for item in order.items) == [
            "Gadget",
            "Widget",
        ]


def test_each_change_in_the_atomic_block_fails_alone():
    example = load_example("concepts/philosophy/always-valid/003.py")
    with _context(example):

        def widget_order():
            return example.Order(
                customer_id="cust-1",
                total=example.Money(amount=20.0, currency="USD"),
                items=[
                    example.OrderItem(
                        product_name="Widget", quantity=2, unit_price=10.0
                    )
                ],
            )

        with pytest.raises(ValidationError) as exc:
            widget_order().total = example.Money(amount=120.0, currency="USD")
        assert set(exc.value.messages) == {"total"}

        with pytest.raises(ValidationError) as exc:
            widget_order().add_items(
                example.OrderItem(product_name="Gadget", quantity=4, unit_price=25.0)
            )
        assert set(exc.value.messages) == {"total"}


# Layer 4: handler guards


def _placed_order(example, hours_ago):
    order = example.Order(
        customer_id="cust-1",
        items=[example.OrderItem(product_name="Widget", quantity=1, unit_price=10.0)],
        placed_at=datetime.now(UTC) - timedelta(hours=hours_ago),
    )
    example.domain.repository_for(example.Order).add(order)
    return order


def _cancel(example, order, cancelled_by, role):
    example.domain.process(
        example.CancelOrder(
            order_id=order.id,
            cancelled_by=cancelled_by,
            cancelled_by_role=role,
            reason="Changed my mind",
        )
    )
    return example.domain.repository_for(example.Order).get(order.id)


def test_customer_can_cancel_their_own_recent_order():
    example = load_example("concepts/philosophy/always-valid/004.py")
    with _context(example):
        order = _cancel(example, _placed_order(example, 1), "cust-1", "customer")
        assert order.status == "cancelled"
        assert order.cancellation_reason == "Changed my mind"


def test_admin_can_cancel_another_customers_order():
    example = load_example("concepts/philosophy/always-valid/004.py")
    with _context(example):
        order = _cancel(example, _placed_order(example, 1), "admin-7", "admin")
        assert order.status == "cancelled"


def test_another_customer_cannot_cancel():
    example = load_example("concepts/philosophy/always-valid/004.py")
    with _context(example):
        order = _placed_order(example, 1)
        with pytest.raises(ValidationError) as exc:
            _cancel(example, order, "cust-2", "customer")
        assert exc.value.messages == {
            "authorization": ["Only the customer or an admin can cancel"]
        }
        stored = example.domain.repository_for(example.Order).get(order.id)
        assert stored.status == "draft"


def test_order_older_than_24_hours_cannot_be_cancelled():
    example = load_example("concepts/philosophy/always-valid/004.py")
    with _context(example):
        order = _placed_order(example, 25)
        with pytest.raises(ValidationError) as exc:
            _cancel(example, order, "cust-1", "customer")
        assert exc.value.messages == {
            "timing": ["Orders cannot be cancelled after 24 hours"]
        }
