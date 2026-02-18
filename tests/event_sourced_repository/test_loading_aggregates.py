from uuid import uuid4

import pytest

from protean.core.aggregate import BaseAggregate, apply
from protean.core.command import BaseCommand
from protean.core.command_handler import BaseCommandHandler
from protean.core.event import BaseEvent
from protean.exceptions import ObjectNotFoundError
from protean.fields import Identifier, String
from protean.fields.basic import Boolean
from protean.utils.globals import current_domain
from protean.utils.mixins import handle


class Register(BaseCommand):
    user_id = Identifier()
    email = String()
    name = String()
    password_hash = String()


class ChangeAddress(BaseCommand):
    user_id = Identifier()
    address = String()


class Registered(BaseEvent):
    user_id = Identifier()
    email = String()
    name = String()
    password_hash = String()


class AddressChanged(BaseEvent):
    user_id = Identifier()
    address = String()


class User(BaseAggregate):
    user_id = Identifier(identifier=True)
    email = String()
    name = String()
    password_hash = String()
    address = String()

    is_registered = Boolean()

    @classmethod
    def register(cls, command: Register) -> "User":
        user = cls(
            user_id=command.user_id,
            email=command.email,
            name=command.name,
            password_hash=command.password_hash,
        )
        user.raise_(
            Registered(
                user_id=command.user_id,
                email=command.email,
                name=command.name,
                password_hash=command.password_hash,
            )
        )

        return user

    def change_address(self, address: String) -> None:
        if address != self.address:
            self.address = address
            self.raise_(AddressChanged(user_id=self.user_id, address=address))

    @apply
    def registered(self, event: Registered) -> None:
        self.user_id = event.user_id
        self.email = event.email
        self.name = event.name
        self.password_hash = event.password_hash
        self.is_registered = True

    @apply
    def address_changed(self, event: AddressChanged) -> None:
        self.address = event.address


class UserCommandHandler(BaseCommandHandler):
    @handle(Register)
    def register_user(self, command: Register) -> None:
        user = User.register(command)
        current_domain.repository_for(User).add(user)

    @handle(ChangeAddress)
    def change_address(self, command: ChangeAddress) -> None:
        user_repo = current_domain.repository_for(User)

        user = user_repo.get(command.user_id)
        user.change_address(command.address)

        user_repo.add(user)


@pytest.fixture(autouse=True)
def register(test_domain):
    test_domain.register(User, is_event_sourced=True)
    test_domain.register(Register, part_of=User)
    test_domain.register(Registered, part_of=User)
    test_domain.register(ChangeAddress, part_of=User)
    test_domain.register(AddressChanged, part_of=User)
    test_domain.register(UserCommandHandler, part_of=User)
    test_domain.init(traverse=False)


@pytest.mark.eventstore
def test_fetching_non_existing_aggregates(test_domain):
    with pytest.raises(ObjectNotFoundError) as exc:
        current_domain.repository_for(User).get("foobar")

    assert exc is not None
    # FIXME errors should be a list
    assert exc.value.args[0] == "`User` object with identifier foobar does not exist."


@pytest.mark.eventstore
def test_loading_aggregates_from_first_event(test_domain):
    identifier = str(uuid4())
    UserCommandHandler().register_user(
        Register(
            user_id=identifier,
            email="john.doe@example.com",
            name="John Doe",
            password_hash="hash",
        )
    )

    user = current_domain.repository_for(User).get(identifier)

    assert user is not None
    assert user == User(
        user_id=identifier,
        email="john.doe@example.com",
        name="John Doe",
        password_hash="hash",
        is_registered=True,
    )

    # Ensure that the first event is applied as well
    assert user.is_registered is True

    assert user._version == 0


@pytest.mark.eventstore
def test_loading_aggregates_from_multiple_events(test_domain):
    identifier = str(uuid4())
    UserCommandHandler().register_user(
        Register(
            user_id=identifier,
            email="john.doe@example.com",
            name="John Doe",
            password_hash="hash",
        )
    )

    UserCommandHandler().change_address(
        ChangeAddress(
            user_id=identifier,
            address="foobar",
        )
    )

    user = current_domain.repository_for(User).get(identifier)

    assert user is not None
    assert user == User(
        user_id=identifier,
        email="john.doe@example.com",
        name="John Doe",
        password_hash="hash",
        address="foobar",
        is_registered=True,
    )

    # Ensure that the first event is applied as well
    assert user.is_registered is True

    assert user._version == 1
