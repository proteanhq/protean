"""The generated ``OrderBase`` and the hand-owned ``Order`` subclass compose into
a working aggregate under ``domain.init(traverse=True)``.

Runs inside the minimal project that ``tests/scaffold/test_generation_gap_seam.py``
lays down, after the planned slice and the hand-edited subclass are written.
"""

from collections.abc import Iterator

import pytest
from myproj.domain import myproj

from protean.exceptions import ValidationError


@pytest.fixture(scope="module", autouse=True)
def _initialised() -> None:
    myproj.init(traverse=True)


@pytest.fixture(autouse=True)
def _context(_initialised: None) -> Iterator[None]:
    with myproj.domain_context():
        yield


@pytest.fixture
def order_class() -> type:
    # Imported after init, so traversal, not this import, loads the slice.
    from myproj.order.aggregate import Order

    return Order


def test_only_the_hand_owned_subclass_registers() -> None:
    names = [record.name for record in myproj.registry.aggregates.values()]

    assert names == ["Order"]


def test_the_base_field_accepts_a_valid_name(order_class: type) -> None:
    order = order_class.create(name="Widget")

    assert order.name == "Widget"
    assert order.id


def test_the_base_field_constraint_holds_on_the_subclass(order_class: type) -> None:
    with pytest.raises(ValidationError):
        order_class(name="x" * 101)


def test_the_generated_create_factory_raises_the_created_event(
    order_class: type,
) -> None:
    order = order_class.create(name="Widget")

    assert [type(event).__name__ for event in order._events] == ["OrderCreated"]


def test_the_subclass_invariant_rejects_a_blank_name(order_class: type) -> None:
    with pytest.raises(ValidationError) as exc:
        order_class(name="   ")

    assert exc.value.messages == {"name": ["name must not be blank"]}
