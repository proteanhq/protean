import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.entity import BaseEntity
from protean.core.event import BaseEvent
from protean.exceptions import IncorrectUsageError
from protean.fields import HasMany, HasOne, String


class User(BaseAggregate):
    email = String()
    name = String()
    account = HasOne("Account")
    addresses = HasMany("Address")


class Account(BaseEntity):
    password_hash = String()


class Address(BaseEntity):
    street = String()
    city = String()
    state = String()
    postal_code = String()


def test_events_cannot_hold_associations():
    with pytest.raises(IncorrectUsageError) as exc:

        class UserRegistered(BaseEvent):
            email = String()
            name = String()
            account = HasOne(Account)

    assert exc.value.args[0] == (
        "Events/Commands cannot have associations. Remove account (HasOne) from class UserRegistered"
    )
