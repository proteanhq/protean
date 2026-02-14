import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.command import BaseCommand
from protean.core.entity import BaseEntity
from protean.exceptions import IncorrectUsageError
from protean.fields import HasMany, HasOne, String


class User(BaseAggregate):
    email: String()
    name: String()
    account = HasOne("Account")
    addresses = HasMany("Address")


class Account(BaseEntity):
    password_hash: String()


class Address(BaseEntity):
    street: String()
    city: String()
    state: String()
    postal_code: String()


def test_commands_cannot_hold_associations():
    with pytest.raises(
        IncorrectUsageError,
        match="Commands and Events can only contain basic field types",
    ):

        class Register(BaseCommand):
            email: String()
            name: String()
            account = HasOne(Account)
