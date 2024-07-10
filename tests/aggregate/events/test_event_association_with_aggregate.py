import pytest

from protean import BaseEvent, BaseEventSourcedAggregate
from protean.exceptions import ConfigurationError
from protean.fields import Identifier, String


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
    status = String(choices=["ACTIVE", "INACTIVE", "ARCHIVED"])

    @classmethod
    def register(cls, user_id, name, email):
        user = cls(user_id=user_id, name=name, email=email)
        user.raise_(UserRegistered(user_id=user_id, name=name, email=email))
        return user

    def activate(self):
        self.raise_(UserActivated(user_id=self.user_id))

    def change_name(self, name):
        self.raise_(UserRenamed(user_id=self.user_id, name=name))


class User2(User):
    pass


class UserUnknownEvent(BaseEvent):
    user_id = Identifier(required=True)


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(User)
    test_domain.register(UserRegistered, part_of=User)
    test_domain.register(UserActivated, part_of=User)
    test_domain.register(UserRenamed, part_of=User)


def test_an_unassociated_event_throws_error(test_domain):
    user = User.register(user_id="1", name="<NAME>", email="<EMAIL>")
    with pytest.raises(ConfigurationError) as exc:
        user.raise_(UserArchived(user_id=user.user_id))

    assert (
        exc.value.args[0] == "Event `UserArchived` should be registered with a domain"
    )


def test_that_event_associated_with_another_aggregate_throws_error(test_domain):
    test_domain.register(User2)
    test_domain.register(UserUnknownEvent, part_of=User2)

    user = User.register(user_id="1", name="<NAME>", email="<EMAIL>")
    with pytest.raises(ConfigurationError) as exc:
        user.raise_(UserUnknownEvent(user_id=user.user_id))

    assert exc.value.args[0] == (
        "Event `UserUnknownEvent` is not associated with aggregate `User`"
    )
