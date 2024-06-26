from enum import Enum

import pytest

from protean import BaseEvent, BaseEventSourcedAggregate, apply
from protean.exceptions import ConfigurationError, IncorrectUsageError
from protean.fields import Identifier, String


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


class UserArchived(BaseEvent):
    user_id = Identifier(required=True)


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

    @apply
    def registered(self, _: UserRegistered):
        self.status = UserStatus.INACTIVE.value

    @apply
    def activated(self, _: UserActivated):
        self.status = UserStatus.ACTIVE.value

    @apply
    def renamed(self, event: UserRenamed):
        self.name = event.name


class Email(BaseEventSourcedAggregate):
    email_id = Identifier(identifier=True)

    @apply
    def registered(self, _: UserRegistered):
        pass


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(User)
    test_domain.register(UserRegistered, part_of=User)
    test_domain.register(UserActivated, part_of=User)
    test_domain.register(UserRenamed, part_of=User)
    test_domain.register(Email)


@pytest.mark.eventstore
def test_that_event_is_associated_with_aggregate():
    assert UserRegistered.meta_.part_of == User
    assert UserActivated.meta_.part_of == User
    assert UserRenamed.meta_.part_of == User


@pytest.mark.eventstore
def test_that_trying_to_associate_an_event_with_multiple_aggregates_throws_an_error(
    test_domain,
):
    test_domain.register(Email)
    with pytest.raises(IncorrectUsageError) as exc:
        test_domain.init(traverse=False)

    assert exc.value.messages == {
        "_event": [
            "Events are associated with multiple event sourced aggregates: "
            "tests.event_sourced_aggregates.test_event_association_with_aggregate.UserRegistered"
        ]
    }


@pytest.mark.eventstore
def test_an_unassociated_event_throws_error(test_domain):
    user = User.register(user_id="1", name="<NAME>", email="<EMAIL>")
    user.raise_(UserArchived(user_id=user.user_id))

    with pytest.raises(ConfigurationError) as exc:
        test_domain.repository_for(User).add(user)

    assert exc.value.args[0] == (
        "No stream name found for `UserArchived`. "
        "Either specify an explicit stream name or associate the event with an aggregate."
    )
