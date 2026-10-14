"""Run the examples on ``docs/concepts/foundations/invariants.md``."""

import pytest

from protean.exceptions import ValidationError
from tests.docs.support import load_example

pytestmark = pytest.mark.no_test_domain


def _context(example):
    example.domain.init(traverse=False)
    return example.domain.domain_context()


def _order(example):
    return example.Order(
        total_amount=100.0,
        items=[example.OrderItem(subtotal=60.0), example.OrderItem(subtotal=40.0)],
    )


def test_order_whose_total_matches_its_items_is_accepted():
    example = load_example("concepts/foundations/invariants/001.py")
    with _context(example):
        order = _order(example)
        assert order.total_amount == 100.0
        assert [item.subtotal for item in order.items] == [60.0, 40.0]


def test_wrong_total_is_rejected_at_once_and_not_set():
    example = load_example("concepts/foundations/invariants/001.py")
    with _context(example):
        order = _order(example)
        with pytest.raises(ValidationError) as exc:
            order.total_amount = 50.0
        assert exc.value.messages == {"_entity": ["Total should be sum of item prices"]}
        assert order.total_amount == 100.0


def test_change_total_alone_prints_the_error_and_keeps_the_total(capsys):
    example = load_example("concepts/foundations/invariants/001.py")
    with _context(example):
        assert example.change_total_alone() == 100.0
    assert capsys.readouterr().out == "['Total should be sum of item prices']\n"


def test_atomic_change_accepts_changes_that_are_valid_together():
    example = load_example("concepts/foundations/invariants/001.py")
    with _context(example):
        order = _order(example)
        example.change_total_with_items(order)
        assert order.total_amount == 120.0
        assert sorted(item.subtotal for item in order.items) == [20.0, 40.0, 60.0]


def test_adding_the_item_alone_is_rejected():
    example = load_example("concepts/foundations/invariants/001.py")
    with _context(example):
        order = _order(example)
        with pytest.raises(ValidationError) as exc:
            order.add_items(example.OrderItem(subtotal=20.0))
        assert exc.value.messages == {"_entity": ["Total should be sum of item prices"]}


def test_atomic_change_rejects_an_invalid_end_state_on_exit():
    example = load_example("concepts/foundations/invariants/001.py")
    with _context(example):
        order = _order(example)
        with pytest.raises(ValidationError) as exc:
            with example.atomic_change(order):
                order.total_amount = 120.0
        assert exc.value.messages == {"_entity": ["Total should be sum of item prices"]}
