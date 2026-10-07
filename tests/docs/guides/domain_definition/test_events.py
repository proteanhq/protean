"""The examples on the events guide behave as the page says."""

from datetime import UTC, datetime

import pytest

from protean.exceptions import ConfigurationError, IncorrectUsageError, ValidationError
from protean.utils.reflection import declared_fields
from tests.docs.support import load_example


def test_user_raises_activated_and_renamed_events():
    example = load_example("guides/domain-definition/events/001.py")
    example.domain.init(traverse=False)

    with example.domain.domain_context():
        user = example.User(name="John Doe", email="john@doe.com")
        user.activate()
        user.change_name("John Doe Jr.")

    assert user.status == "ACTIVE"
    assert [type(event) for event in user._events] == [
        example.UserActivated,
        example.UserRenamed,
    ]
    assert user._events[0].user_id == user.id
    assert user._events[1].name == "John Doe Jr."


def test_events_are_immutable():
    example = load_example("guides/domain-definition/events/001.py")
    example.domain.init(traverse=False)

    with example.domain.domain_context():
        user = example.User(name="John Doe", email="john@doe.com", status="ACTIVE")
        renamed = example.UserRenamed(user_id=user.id, name="John Doe Jr.")

        with pytest.raises(IncorrectUsageError) as exc:
            renamed.name = "John Doe Sr."

    assert "immutable" in str(exc.value)
    assert renamed.name == "John Doe Jr."


def test_event_metadata_carries_the_configured_version(capsys):
    example = load_example("guides/domain-definition/events/002.py")

    printed = capsys.readouterr().out
    assert '"type": "Authentication.UserLoggedIn.v1"' in printed
    assert '"type": "Authentication.UserActivated.v2"' in printed
    assert '"version": 1,' in printed
    assert '"version": 2,' in printed

    with example.domain.domain_context():
        user = example.User(id="1", email="jane@example.com", name="Jane")
        user.login()

    event = user._events[0]
    assert event.payload == {"user_id": "1"}
    assert event._metadata.headers.id == "authentication::user-1-0.1"
    assert event._metadata.headers.stream == "authentication::user-1"
    assert event._metadata.domain.sequence_id == "0.1"


def test_fact_event_carries_the_whole_user(capsys):
    load_example("guides/domain-definition/events/003.py")

    printed = capsys.readouterr().out
    assert '"name": "John Doe"' in printed
    assert '"email": "john.doe@example.com"' in printed
    assert '"type": "Authentication.UserFactEvent.v1"' in printed


def test_concrete_events_inherit_the_abstract_base_fields():
    example = load_example("guides/domain-definition/events/004.py")
    example.domain.init(traverse=False)

    assert example.BaseOrderEvent.meta_.abstract is True
    assert {"order_id", "occurred_at", "customer_name"} <= set(
        declared_fields(example.OrderPlaced)
    )
    assert {"order_id", "occurred_at", "reason"} <= set(
        declared_fields(example.OrderCancelled)
    )

    with example.domain.domain_context():
        placed = example.OrderPlaced(
            order_id="1", occurred_at=datetime.now(UTC), customer_name="Jane"
        )

    assert placed.order_id == "1"
    assert placed.customer_name == "Jane"


def test_concrete_event_rejects_a_missing_inherited_field():
    example = load_example("guides/domain-definition/events/004.py")
    example.domain.init(traverse=False)

    with example.domain.domain_context(), pytest.raises(ValidationError) as exc:
        example.OrderCancelled(reason="Out of stock")

    assert "order_id" in exc.value.messages
    assert "occurred_at" in exc.value.messages


def test_abstract_event_cannot_be_raised():
    example = load_example("guides/domain-definition/events/004.py")
    example.domain.init(traverse=False)

    with example.domain.domain_context():
        order = example.Order(customer_name="Jane")
        base = example.BaseOrderEvent(order_id="1", occurred_at=datetime.now(UTC))

        with pytest.raises(ConfigurationError):
            order.raise_(base)


def test_events_can_be_set_to_sync_processing():
    example = load_example("guides/domain-definition/events/005.py")
    example.domain.init(traverse=False)

    assert example.domain.config["event_processing"] == "sync"


def test_event_and_command_processing_are_set_separately():
    example = load_example("guides/domain-definition/events/006.py")
    example.domain.init(traverse=False)

    assert example.domain.config["event_processing"] == "async"
    assert example.domain.config["command_processing"] == "sync"


def test_version_set_with_the_class_attribute():
    example = load_example("guides/domain-definition/events/007.py")
    example.domain.init(traverse=False)

    with example.domain.domain_context():
        event = example.UserActivated(user_id="1", activated_at=datetime.now(UTC))

    assert event._metadata.domain.version == 2
    assert event._metadata.headers.type == "Authentication.UserActivated.v2"


def test_version_set_with_the_decorator_option():
    example = load_example("guides/domain-definition/events/008.py")
    example.domain.init(traverse=False)

    with example.domain.domain_context():
        event = example.UserActivated(user_id="1", activated_at=datetime.now(UTC))

    assert event._metadata.domain.version == 2
    assert event._metadata.headers.type == "Authentication.UserActivated.v2"


def test_declaring_the_version_both_ways_is_rejected():
    example = load_example("guides/domain-definition/events/008.py")

    with pytest.raises(IncorrectUsageError) as exc:

        @example.domain.event(part_of=example.User, version=2)
        class UserDeactivated:
            __version__ = 2

    assert "declares its version twice" in str(exc.value)


def test_placing_an_order_raises_order_placed():
    example = load_example("guides/domain-definition/events/009.py")
    example.domain.init(traverse=False)

    with example.domain.domain_context():
        order = example.Order(customer_name="Jane")
        order.place()

    assert order.status == "PLACED"
    assert len(order._events) == 1
    event = order._events[0]
    assert isinstance(event, example.OrderPlaced)
    assert event.order_id == order.id
    assert event.customer_name == "Jane"


def test_saving_the_order_runs_the_handler_when_processing_is_sync(capsys):
    example = load_example("guides/domain-definition/events/009.py")
    example.domain.config["event_processing"] = "sync"
    example.domain.init(traverse=False)

    with example.domain.domain_context():
        order = example.Order(customer_name="Jane")
        order.place()
        example.domain.repository_for(example.Order).add(order)

    assert f"Order {order.id} placed for Jane" in capsys.readouterr().out
