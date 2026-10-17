from uuid import uuid4

import pytest

from protean import apply, handle
from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.core.event_handler import BaseEventHandler
from protean.fields import String
from protean.fields.basic import Identifier
from protean.testing import drain
from protean.utils import Processing
from protean.utils.eventing import Message


class Registered(BaseEvent):
    user_id: Identifier(identifier=True)
    email: String()


class User(BaseAggregate):
    user_id: Identifier(identifier=True)
    email: String()

    @classmethod
    def register(cls, user_id, email):
        user = cls(user_id=user_id, email=email)
        user.raise_(Registered(user_id=user_id, email=email))
        return user

    @apply
    def on_registered(self, event: Registered) -> None:
        self.email = event.email


seen_positions: list[tuple[int | None, int | None]] = []


class PositionRecorder(BaseEventHandler):
    @handle(Registered)
    def record(self, event: Registered) -> None:
        store_meta = event._metadata.event_store
        seen_positions.append((store_meta.position, store_meta.global_position))


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    # Async processing keeps the handler out of the commit, so a test can
    # call it with the message read back from the store.
    test_domain.config["event_processing"] = Processing.ASYNC.value
    test_domain.register(User, event_sourced=True)
    test_domain.register(Registered, part_of=User)
    test_domain.register(PositionRecorder, part_of=User)
    test_domain.init(traverse=False)
    seen_positions.clear()


def _register_users(test_domain, count):
    user_ids = [str(uuid4()) for _ in range(count)]
    for user_id in user_ids:
        test_domain.repository_for(User).add(
            User.register(user_id=user_id, email=f"{user_id}@example.com")
        )
    return user_ids


def _stored_message(test_domain, user_id):
    messages = test_domain.event_store.store.read(f"test::user-{user_id}")
    assert len(messages) == 1
    return messages[0]


def test_a_freshly_raised_event_has_no_store_positions():
    event = Registered(user_id=str(uuid4()), email="ada@example.com")

    assert event._metadata.event_store is None


def test_an_event_rebuilt_from_the_store_keeps_its_positions(test_domain):
    (user_id,) = _register_users(test_domain, 1)
    message = _stored_message(test_domain, user_id)
    assert message.metadata.event_store is not None
    assert message.metadata.event_store.position == 0

    event = message.to_domain_object()

    assert event._metadata.event_store == message.metadata.event_store


def test_a_handler_sees_the_stored_positions(test_domain):
    first_id, second_id = _register_users(test_domain, 2)
    first = _stored_message(test_domain, first_id)
    second = _stored_message(test_domain, second_id)

    PositionRecorder._handle(first)
    PositionRecorder._handle(second)

    assert first.metadata.event_store.global_position < (
        second.metadata.event_store.global_position
    )
    assert seen_positions == [
        (0, first.metadata.event_store.global_position),
        (0, second.metadata.event_store.global_position),
    ]


def test_the_engine_hands_a_handler_the_stored_positions(test_domain):
    first_id, second_id = _register_users(test_domain, 2)
    first = _stored_message(test_domain, first_id)
    second = _stored_message(test_domain, second_id)

    drain(test_domain, until=lambda: len(seen_positions) == 2)

    assert seen_positions == [
        (0, first.metadata.event_store.global_position),
        (0, second.metadata.event_store.global_position),
    ]


def test_a_new_event_built_from_a_rebuilt_ones_metadata_has_no_positions(
    test_domain,
):
    (user_id,) = _register_users(test_domain, 1)
    rebuilt = _stored_message(test_domain, user_id).to_domain_object()
    assert rebuilt._metadata.event_store is not None

    copy = Registered(rebuilt.payload, _metadata=rebuilt._metadata)

    assert copy._metadata.event_store is None


def test_writing_a_rebuilt_event_again_stores_the_new_positions(test_domain):
    (user_id,) = _register_users(test_domain, 1)
    stream = f"test::user-{user_id}"
    original = _stored_message(test_domain, user_id)
    rebuilt = original.to_domain_object()
    assert rebuilt._metadata.event_store is not None
    # The stream already holds the original at version 0.
    second_write = Registered(
        rebuilt.payload,
        _metadata=rebuilt._metadata,
        _expected_version=0,
        _rebuild=True,
    )
    assert second_write._metadata.event_store == original.metadata.event_store

    test_domain.event_store.store.append(second_write)

    raw_rows = test_domain.event_store.store._read(stream)
    assert len(raw_rows) == 2
    assert [row["metadata"].get("event_store") for row in raw_rows] == [None, None]

    rewritten = test_domain.event_store.store.read(stream)[1]
    assert rewritten.metadata.event_store.position == 1
    assert rewritten.metadata.event_store.global_position > (
        original.metadata.event_store.global_position
    )


def test_a_message_built_from_a_rebuilt_event_carries_no_positions(test_domain):
    (user_id,) = _register_users(test_domain, 1)
    rebuilt = _stored_message(test_domain, user_id).to_domain_object()

    message = Message.from_domain_object(rebuilt)

    assert message.metadata.event_store is None
