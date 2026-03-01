"""Tests that modifying multiple aggregate types in a single UnitOfWork
logs a warning, nudging toward one-aggregate-per-transaction."""

import logging

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.core.unit_of_work import UnitOfWork
from protean.fields import String
from protean.fields.basic import Identifier


# ── Domain elements ─────────────────────────────────────────────────────


class UserRegistered(BaseEvent):
    id = Identifier()
    name = String()


class User(BaseAggregate):
    name: String(required=True, max_length=100)

    def register(self) -> None:
        self.raise_(UserRegistered(id=self.id, name=self.name))


class OrderPlaced(BaseEvent):
    id = Identifier()
    description = String()


class Order(BaseAggregate):
    description: String(required=True, max_length=200)

    def place(self) -> None:
        self.raise_(OrderPlaced(id=self.id, description=self.description))


# ── Tests ────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(User)
    test_domain.register(UserRegistered, part_of=User)
    test_domain.register(Order)
    test_domain.register(OrderPlaced, part_of=Order)
    test_domain.init(traverse=False)


@pytest.mark.eventstore
def test_multi_aggregate_uow_logs_warning(test_domain, caplog):
    """Modifying two aggregate types in one UoW should log a warning."""
    with caplog.at_level(logging.WARNING, logger="protean.core.unit_of_work"):
        with UnitOfWork():
            user = User(name="Alice")
            user.register()
            test_domain.repository_for(User).add(user)

            order = Order(description="Widget")
            order.place()
            test_domain.repository_for(Order).add(order)

    warning_messages = [
        r.message for r in caplog.records if r.levelno == logging.WARNING
    ]
    assert any("Multiple aggregate types" in msg for msg in warning_messages)
    # Both aggregate class names should appear in the warning
    matching = [msg for msg in warning_messages if "Multiple aggregate types" in msg]
    assert "Order" in matching[0]
    assert "User" in matching[0]


@pytest.mark.eventstore
def test_single_aggregate_uow_no_warning(test_domain, caplog):
    """Modifying only one aggregate type should not produce a warning."""
    with caplog.at_level(logging.WARNING, logger="protean.core.unit_of_work"):
        with UnitOfWork():
            user = User(name="Bob")
            user.register()
            test_domain.repository_for(User).add(user)

    warning_messages = [
        r.message for r in caplog.records if r.levelno == logging.WARNING
    ]
    assert not any("Multiple aggregate types" in msg for msg in warning_messages)


@pytest.mark.eventstore
def test_reading_multiple_aggregates_no_warning(test_domain, caplog):
    """Loading (reading) multiple aggregate types without events should not warn."""
    # Persist one of each first
    with UnitOfWork():
        user = User(name="Charlie")
        user.register()
        test_domain.repository_for(User).add(user)

    with UnitOfWork():
        order = Order(description="Gadget")
        order.place()
        test_domain.repository_for(Order).add(order)

    # Now read both in a single UoW — no events raised
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="protean.core.unit_of_work"):
        with UnitOfWork():
            test_domain.repository_for(User).get(user.id)
            test_domain.repository_for(Order).get(order.id)

    warning_messages = [
        r.message for r in caplog.records if r.levelno == logging.WARNING
    ]
    assert not any("Multiple aggregate types" in msg for msg in warning_messages)
