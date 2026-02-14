from pydantic import Field

from protean.core.aggregate import BaseAggregate
from protean.core.command import BaseCommand
from protean.core.event import BaseEvent
from protean.core.value_object import BaseValueObject
from protean.utils.reflection import declared_fields, id_field


class Balance(BaseValueObject):
    currency: str
    amount: float


class User(BaseAggregate):
    name: str | None = None


class Account(BaseAggregate):
    account_id: str = Field(json_schema_extra={"identifier": True})


class Register(BaseCommand):
    user_id: str = Field(json_schema_extra={"identifier": True})


class SendEmail(BaseCommand):
    email: str | None = None


class Registered(BaseEvent):
    user_id: str = Field(json_schema_extra={"identifier": True})


class EmailSent(BaseEvent):
    email: str | None = None


def test_id_field_values():
    assert id_field(Balance) is None
    assert id_field(User) is declared_fields(User)["id"]
    assert id_field(Account) is declared_fields(Account)["account_id"]
    assert id_field(Registered) is declared_fields(Registered)["user_id"]
    assert id_field(EmailSent) is None
    assert id_field(Register) is declared_fields(Register)["user_id"]
    assert id_field(SendEmail) is None
