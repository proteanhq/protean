import pytest

from pydantic import PydanticUserError

from protean.core.aggregate import BaseAggregate
from protean.core.entity import BaseEntity
from protean.core.event import BaseEvent
from protean.fields import HasMany, HasOne


class User(BaseAggregate):
    email: str | None = None
    name: str | None = None
    account = HasOne("Account")
    addresses = HasMany("Address")


class Account(BaseEntity):
    password_hash: str | None = None


class Address(BaseEntity):
    street: str | None = None
    city: str | None = None
    state: str | None = None
    postal_code: str | None = None


def test_events_cannot_hold_associations():
    """With Pydantic-based BaseEvent, non-annotated association fields
    are rejected by Pydantic itself as non-annotated attributes."""
    with pytest.raises(PydanticUserError, match="non-annotated attribute was detected"):

        class UserRegistered(BaseEvent):
            email: str | None = None
            name: str | None = None
            account = HasOne(Account)
