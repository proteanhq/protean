from __future__ import annotations

from uuid import uuid4

import pytest

from protean import (
    BaseCommandHandler,
    BaseEvent,
    BaseEventSourcedAggregate,
    apply,
    handle,
)
from protean.core.command import BaseCommand
from protean.fields import Identifier, String
from protean.globals import current_domain


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


class User(BaseEventSourcedAggregate):
    user_id = Identifier(identifier=True)  # FIXME Auto-attach ID attribute
    email = String()
    name = String()
    password_hash = String()
    address = String()

    @classmethod
    def register(cls, command: Register) -> User:
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

    @apply(AddressChanged)
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

    class Meta:
        aggregate_cls = User


@pytest.fixture(autouse=True)
def register(test_domain):
    test_domain.register(User)
    test_domain.register(UserCommandHandler)


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
    )


def test_loading_aggregates_from_events(test_domain):
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
    )
