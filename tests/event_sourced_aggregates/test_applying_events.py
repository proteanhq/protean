from enum import Enum
from uuid import uuid4

import pytest

from protean import BaseEvent, BaseEventSourcedAggregate, apply
from protean.exceptions import IncorrectUsageError
from protean.fields import Identifier, String
from protean.utils.mixins import Message


class UserStatus(Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    ARCHIVED = "ARCHIVED"


class UserRegistered(BaseEvent):
    user_id = Identifier(required=True)
    name = String(max_length=50, required=True)
    email = String(required=True)


class UserActivated(BaseEvent):
    user_id = Identifier(required=True)


class UserRenamed(BaseEvent):
    user_id = Identifier(required=True)
    name = String(required=True, max_length=50)


class User(BaseEventSourcedAggregate):
    user_id = Identifier(identifier=True)
    name = String(max_length=50, required=True)
    email = String(required=True)
    status = String(choices=UserStatus)

    @classmethod
    def register(cls, user_id, name, email):
        user = cls(user_id=user_id, name=name, email=email)
        user.raise_(UserRegistered(user_id=user_id, name=name, email=email))
        return user

    def activate(self):
        self.raise_(UserActivated(user_id=self.user_id))

    def change_name(self, name):
        self.raise_(UserRenamed(user_id=self.user_id, name=name))

    @apply(UserRegistered)
    def registered(self, _: UserRegistered):
        self.status = UserStatus.INACTIVE.value

    @apply(UserActivated)
    def activated(self, _: UserActivated):
        self.status = UserStatus.ACTIVE.value

    @apply(UserRenamed)
    def renamed(self, event: UserRenamed):
        self.name = event.name


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(User)


@pytest.mark.eventstore
def test_applying_events():
    identifier = str(uuid4())

    registered = UserRegistered(
        user_id=identifier, name="John Doe", email="john.doe@example.com"
    )
    activated = UserActivated(user_id=identifier)
    renamed = UserRenamed(user_id=identifier, name="Jane Doe")

    user = User.register(**registered.to_dict())

    msg_registered = Message.to_aggregate_event_message(user, registered)
    user._apply(msg_registered.to_dict())
    assert user.status == UserStatus.INACTIVE.value

    msg_activated = Message.to_aggregate_event_message(user, activated)
    user._apply(msg_activated.to_dict())
    assert user.status == UserStatus.ACTIVE.value

    msg_renamed = Message.to_aggregate_event_message(user, renamed)
    user._apply(msg_renamed.to_dict())
    assert user.name == "Jane Doe"


def test_that_apply_decorator_without_event_cls_raises_error():
    class Sent(BaseEvent):
        email_id = Identifier()

    with pytest.raises(IncorrectUsageError) as exc:

        class _(BaseEventSourcedAggregate):
            email_id = Identifier(identifier=True)

            @apply
            def sent(self, _: Sent) -> None:
                pass

    assert exc.value.messages == {
        "_entity": ["Apply method is missing Event class argument"]
    }
