import pytest

from uuid import uuid4

from pydantic import Field

from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.exceptions import ConfigurationError


class UserRegistered(BaseEvent):
    user_id: str
    name: str
    email: str


class UserActivated(BaseEvent):
    user_id: str


class UserRenamed(BaseEvent):
    user_id: str
    name: str


class UserArchived(BaseEvent):
    user_id: str


class User(BaseAggregate):
    user_id: str = Field(
        default_factory=lambda: str(uuid4()),
        json_schema_extra={"identifier": True},
    )
    name: str
    email: str
    status: str | None = None

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
    user_id: str


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(User, is_event_sourced=True)
    test_domain.register(UserRegistered, part_of=User)
    test_domain.register(UserActivated, part_of=User)
    test_domain.register(UserRenamed, part_of=User)
    test_domain.init(traverse=False)


def test_an_unassociated_event_throws_error(test_domain):
    user = User.register(user_id="1", name="<NAME>", email="<EMAIL>")
    with pytest.raises(ConfigurationError) as exc:
        user.raise_(UserArchived(user_id=user.user_id))

    assert exc.value.args[0] == "`UserArchived` should be registered with a domain"


def test_that_event_associated_with_another_aggregate_throws_error(test_domain):
    test_domain.register(User2, is_event_sourced=True)
    test_domain.register(UserUnknownEvent, part_of=User2)
    test_domain.init(traverse=False)

    user = User.register(user_id="1", name="<NAME>", email="<EMAIL>")
    with pytest.raises(ConfigurationError) as exc:
        user.raise_(UserUnknownEvent(user_id=user.user_id))

    assert exc.value.args[0] == (
        "Event `UserUnknownEvent` is not associated with aggregate `User`"
    )
