from protean import BaseEvent
from protean.fields import Identifier, String
from protean.reflection import has_id_field, id_field


class Registered(BaseEvent):
    user_id = Identifier(identifier=True)
    email = String()
    name = String()


class EmailSent(BaseEvent):
    to = String()
    subject = String()
    content = String()


def test_id_field_for_command_with_identifier():
    assert has_id_field(Registered) is True

    field = id_field(Registered)

    assert field is not None
    assert field.field_name == "user_id"


def test_id_field_for_command_without_identifier():
    assert has_id_field(EmailSent) is False
