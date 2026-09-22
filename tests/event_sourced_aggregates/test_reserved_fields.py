"""Runtime behavior of the ``reserved`` option on an event-sourced aggregate.

Removing a field from an event-sourced aggregate is safe only when the aggregate
declares the field name in ``reserved``. A retained ``@apply`` handler for a
retired event can still assign the removed name; replay must tolerate it by
dropping the value, while the live ``raise_`` path still raises.
"""

from uuid import uuid4

import pytest
from pydantic import ValidationError as PydanticValidationError

from protean.core.aggregate import BaseAggregate, apply
from protean.core.entity import BaseEntity
from protean.core.event import BaseEvent
from protean.core.value_object import BaseValueObject
from protean.exceptions import IncorrectUsageError
from protean.fields import Float, HasMany, Identifier, String, ValueObject


class OrderPlaced(BaseEvent):
    order_id: Identifier(required=True)
    amount: Float(required=True)


class OrderNoted(BaseEvent):
    """A retired event whose handler is kept so history still replays. Its
    payload still carries ``note``, a field since removed from the aggregate."""

    order_id: Identifier(required=True)
    note: String(required=True)


class OrderTypoed(BaseEvent):
    order_id: Identifier(required=True)
    value: String(required=True)


class Address(BaseValueObject):
    street: String(max_length=100)
    zip_code: String(max_length=10)


class LineItem(BaseEntity):
    name: String(max_length=50)


class Order(BaseAggregate):
    order_id: Identifier(identifier=True)
    amount: Float()

    @apply
    def placed(self, event: OrderPlaced):
        self.order_id = event.order_id
        self.amount = event.amount

    @apply
    def noted(self, event: OrderNoted):
        # ``note`` was a field once; it is removed now but reserved, so replay
        # drops this assignment instead of raising.
        self.note = event.note

    @apply
    def typoed(self, event: OrderTypoed):
        # ``ghost`` is neither a field nor reserved — a typo in a retained
        # handler. Replay must still raise on it.
        self.ghost = event.value


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Order, event_sourced=True, reserved=["note"])
    test_domain.register(OrderPlaced, part_of=Order)
    test_domain.register(OrderNoted, part_of=Order)
    test_domain.register(OrderTypoed, part_of=Order)
    test_domain.init(traverse=False)


def _placed():
    return OrderPlaced(order_id=str(uuid4()), amount=100.0)


def test_replay_drops_assignment_to_a_reserved_name():
    placed = _placed()
    noted = OrderNoted(order_id=placed.order_id, note="a kept note")

    order = Order.from_events([placed, noted])

    assert order.order_id == placed.order_id
    assert order.amount == 100.0
    # The reserved name never lands on the rebuilt aggregate.
    assert not hasattr(order, "note")


def test_snapshot_catchup_replay_also_drops_with_invariant_checks_enabled():
    """The snapshot-catchup path applies events through ``_apply`` on a
    live-constructed aggregate, where ``_disable_invariant_checks`` is False.
    The drop is gated on the replay flag ``_apply`` sets, not on that flag, so
    it still drops."""
    placed = _placed()
    order = Order.from_events([placed])
    # After ``from_events`` the aggregate is live: invariant checks are on.
    assert order._disable_invariant_checks is False

    order._apply(OrderNoted(order_id=placed.order_id, note="caught up"))

    assert not hasattr(order, "note")
    # The flag is reset after the event applies.
    assert order._replaying is False


def test_live_path_still_raises_on_a_removed_field():
    """Raising the event on the live path applies its handler directly, with no
    replay flag set, so the assignment to the removed field raises."""
    placed = _placed()
    order = Order.from_events([placed])

    with pytest.raises(PydanticValidationError, match="no_such_attribute"):
        order.raise_(OrderNoted(order_id=placed.order_id, note="live write"))


def test_replay_still_raises_on_a_name_that_is_neither_field_nor_reserved():
    placed = _placed()
    typoed = OrderTypoed(order_id=placed.order_id, value="oops")

    with pytest.raises(PydanticValidationError, match="no_such_attribute"):
        Order.from_events([placed, typoed])


def test_replaying_flag_is_reset_when_a_handler_raises_mid_apply():
    """An exception mid-replay must not leave a live aggregate stuck in replay
    mode. The ``finally`` in ``_apply`` resets ``_replaying`` even when the
    handler raises, so a later live write to a removed field still raises."""
    placed = _placed()
    order = Order.from_events([placed])

    with pytest.raises(PydanticValidationError):
        order._apply(OrderTypoed(order_id=placed.order_id, value="oops"))

    assert order._replaying is False


def test_declaring_a_field_over_a_reserved_name_raises(test_domain):
    with pytest.raises(IncorrectUsageError) as exc:

        @test_domain.aggregate(event_sourced=True, reserved=["note"])
        class Bad(BaseAggregate):
            bad_id: Identifier(identifier=True)
            note: String()

    assert "reserved" in str(exc.value)


def test_declaring_a_value_object_field_over_a_reserved_name_raises(test_domain):
    """A live value-object field lives in ``declared_fields`` but not in
    ``model_fields``. The collision check must scan the former so this raises
    instead of silently dropping ``address`` on every replay."""
    with pytest.raises(IncorrectUsageError) as exc:

        @test_domain.aggregate(event_sourced=True, reserved=["address"])
        class Bad(BaseAggregate):
            bad_id: Identifier(identifier=True)
            address = ValueObject(Address)

    assert "reserved" in str(exc.value)


def test_declaring_an_association_field_over_a_reserved_name_raises(test_domain):
    """An association field (``HasMany``) also lives only in
    ``declared_fields``, so it must be caught by the collision check too."""
    with pytest.raises(IncorrectUsageError) as exc:

        @test_domain.aggregate(event_sourced=True, reserved=["items"])
        class Bad(BaseAggregate):
            bad_id: Identifier(identifier=True)
            items = HasMany(LineItem)

    assert "reserved" in str(exc.value)


def test_reserved_rejects_a_non_string_element(test_domain):
    with pytest.raises(IncorrectUsageError, match="field names"):

        @test_domain.aggregate(event_sourced=True, reserved=["note", 123])
        class Bad(BaseAggregate):
            bad_id: Identifier(identifier=True)


def test_reserved_rejects_a_private_name(test_domain):
    """Reserving `_replaying` would make `__setattr__` drop the `finally` reset
    in `_apply`, leaving every aggregate of this class stuck in replay mode."""
    with pytest.raises(IncorrectUsageError, match="not field names"):

        @test_domain.aggregate(event_sourced=True, reserved=["_replaying"])
        class Bad(BaseAggregate):
            bad_id: Identifier(identifier=True)


def test_reserved_rejects_a_name_that_is_not_an_identifier(test_domain):
    with pytest.raises(IncorrectUsageError, match="not field names"):

        @test_domain.aggregate(event_sourced=True, reserved=["", "note"])
        class Bad(BaseAggregate):
            bad_id: Identifier(identifier=True)


def test_reserved_accepts_a_bare_string(test_domain):
    @test_domain.aggregate(event_sourced=True, reserved="note")
    class Wrapped(BaseAggregate):
        wrapped_id: Identifier(identifier=True)

    assert Wrapped.meta_.reserved == ("note",)
