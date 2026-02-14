from pydantic import Field

from protean.core.event import BaseEvent
from protean.utils.reflection import has_id_field, id_field


class Registered(BaseEvent):
    user_id: str = Field(json_schema_extra={"identifier": True})
    email: str | None = None
    name: str | None = None


class EmailSent(BaseEvent):
    to: str | None = None
    subject: str | None = None
    content: str | None = None


def test_id_field_for_command_with_identifier():
    assert has_id_field(Registered) is True

    field = id_field(Registered)

    assert field is not None
    assert field.field_name == "user_id"


def test_id_field_for_command_without_identifier():
    assert has_id_field(EmailSent) is False
