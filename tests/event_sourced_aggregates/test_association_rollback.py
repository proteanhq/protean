"""A failed post-invariant undoes an association change on an event-sourced aggregate."""

from uuid import uuid4

import pytest

import protean.core.entity as entity_module
from protean.core.aggregate import BaseAggregate, apply
from protean.core.entity import BaseEntity, invariant
from protean.core.event import BaseEvent
from protean.exceptions import ValidationError
from protean.fields import HasMany, Identifier, String


class CartOpened(BaseEvent):
    cart_id: Identifier(required=True)


class LineAdded(BaseEvent):
    cart_id: Identifier(required=True)
    name: String(required=True)


class Cart(BaseAggregate):
    cart_id: Identifier(identifier=True)
    lines = HasMany("Line")

    @classmethod
    def open(cls, cart_id):
        cart = cls._create_new(cart_id=cart_id)
        cart.raise_(CartOpened(cart_id=cart_id))
        return cart

    @invariant.post
    def at_most_one_line(self):
        if len(self.lines) > 1:
            raise ValidationError({"lines": ["Only one line is allowed"]})

    @apply
    def opened(self, event: CartOpened):
        self.cart_id = event.cart_id

    @apply
    def line_added(self, event: LineAdded):
        self.add_lines(Line(name=event.name))


class Line(BaseEntity):
    name: String(max_length=50)


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Cart, event_sourced=True)
    test_domain.register(Line, part_of=Cart)
    test_domain.register(CartOpened, part_of=Cart)
    test_domain.register(LineAdded, part_of=Cart)
    test_domain.init(traverse=False)


@pytest.fixture
def cart():
    cart = Cart.open(cart_id=str(uuid4()))
    cart.raise_(LineAdded(cart_id=cart.cart_id, name="first"))
    return cart


def test_failed_add_on_an_event_sourced_aggregate_keeps_the_old_lines(cart):
    lines_before = list(cart.lines)
    extra = Line(name="extra")

    with pytest.raises(ValidationError):
        cart.add_lines(extra)

    assert cart.lines == lines_before
    assert extra._root is None


def test_rejected_event_leaves_the_lines_as_they_were(cart):
    lines_before = list(cart.lines)
    events_before = list(cart._events)

    with pytest.raises(ValidationError):
        cart.raise_(LineAdded(cart_id=cart.cart_id, name="second"))

    assert cart.lines == lines_before
    assert cart._events == events_before
    assert cart._temp_cache["lines"].added.keys() == {lines_before[0].id}


def test_replay_takes_no_snapshots(cart, monkeypatch):
    taken = []
    real_snapshot = entity_module._snapshot_entity

    def counting_snapshot(*args, **kwargs):
        taken.append(args[0])
        return real_snapshot(*args, **kwargs)

    monkeypatch.setattr(entity_module, "_snapshot_entity", counting_snapshot)

    replayed = Cart.from_events(list(cart._events))

    assert [line.name for line in replayed.lines] == ["first"]
    assert taken == []
