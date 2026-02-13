from protean.core.aggregate import _LegacyBaseAggregate as BaseAggregate
from protean.core.command import _LegacyBaseCommand as BaseCommand
from protean.core.event import _LegacyBaseEvent as BaseEvent
from protean.core.value_object import _LegacyBaseValueObject as BaseValueObject
from protean.fields import Float, Identifier, String
from protean.utils.reflection import declared_fields, id_field


class Balance(BaseValueObject):
    currency = String(max_length=3, required=True)
    amount = Float(required=True)


class User(BaseAggregate):
    name = String()


class Account(BaseAggregate):
    account_id = String(identifier=True)


class Register(BaseCommand):
    user_id = Identifier(identifier=True)


class SendEmail(BaseCommand):
    email = String()


class Registered(BaseEvent):
    user_id = Identifier(identifier=True)


class EmailSent(BaseEvent):
    email = String()


def test_id_field_values():
    assert id_field(Balance) is None
    assert id_field(User) is declared_fields(User)["id"]
    assert id_field(Account) is declared_fields(Account)["account_id"]
    assert id_field(Registered) is declared_fields(Registered)["user_id"]
    assert id_field(EmailSent) is None
    assert id_field(Register) is declared_fields(Register)["user_id"]
    assert id_field(SendEmail) is None
