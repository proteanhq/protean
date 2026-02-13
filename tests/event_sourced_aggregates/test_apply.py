from enum import Enum
from uuid import uuid4

import pytest

from protean.core.aggregate import BaseAggregate, apply
from protean.core.command import _LegacyBaseCommand as BaseCommand
from protean.core.event import _LegacyBaseEvent as BaseEvent
from protean.exceptions import IncorrectUsageError
from protean.fields import Identifier, String
from protean.utils import fqn


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


class User(BaseAggregate):
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


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(User, is_event_sourced=True)
    test_domain.register(UserRegistered, part_of=User)
    test_domain.register(UserActivated, part_of=User)
    test_domain.register(UserRenamed, part_of=User)
    test_domain.init(traverse=False)


def test_apply_decorator_marks_methods():
    for method in [User.registered, User.activated, User.renamed]:
        assert hasattr(method, "_event_cls")

    assert User._projections[fqn(UserRegistered)] == {User.registered}
    assert User._projections[fqn(UserActivated)] == {User.activated}
    assert User._projections[fqn(UserRenamed)] == {User.renamed}

    assert User._events_cls_map[fqn(UserRegistered)] == UserRegistered
    assert User._events_cls_map[fqn(UserActivated)] == UserActivated
    assert User._events_cls_map[fqn(UserRenamed)] == UserRenamed


def test_apply_decorator_method_should_have_exactly_one_argument():
    with pytest.raises(IncorrectUsageError) as exc:

        class Sent(BaseEvent):
            email_id = Identifier()

        class _(BaseAggregate):
            email_id = Identifier(identifier=True)

            @apply
            def sent(self, event: Sent, _: str) -> None:
                pass

    assert (
        exc.value.args[0] == "Handler method `sent` has incorrect number of arguments"
    )


def test_that_apply_decorator_without_event_cls_raises_error():
    class Send(BaseCommand):
        email_id = Identifier()

    # Argument should be an event class
    with pytest.raises(IncorrectUsageError) as exc:

        class _(BaseAggregate):
            email_id = Identifier(identifier=True)

            @apply
            def sent(self, _: Send) -> None:
                pass

    assert (
        exc.value.args[0]
        == "Apply method `sent` should accept an argument annotated with the Event class"
    )

    # Argument should be annotated
    with pytest.raises(IncorrectUsageError) as exc:

        class _(BaseAggregate):
            email_id = Identifier(identifier=True)

            @apply
            def sent(self, _) -> None:
                pass

    assert (
        exc.value.args[0]
        == "Apply method `sent` should accept an argument annotated with the Event class"
    )

    # Argument should be supplied
    with pytest.raises(IncorrectUsageError) as exc:

        class _(BaseAggregate):
            email_id = Identifier(identifier=True)

            @apply
            def sent(self) -> None:
                pass

    assert (
        exc.value.args[0]
        == "Apply method `sent` should accept an argument annotated with the Event class"
    )


def test_event_to_be_applied_should_have_a_projection(test_domain):
    class UserArchived(BaseEvent):
        user_id = Identifier(required=True)

    test_domain.register(UserArchived, part_of=User)
    test_domain.init(traverse=False)

    user = User(user_id=str(uuid4()), name="<NAME>", email="<EMAIL>")

    with pytest.raises(NotImplementedError) as exc:
        user._apply(UserArchived(user_id=user.user_id))

    assert exc.value.args[0].startswith("No handler registered for event")
