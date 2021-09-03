from protean.fields import Auto
from protean.infra.eventing import EventLog
from protean.reflection import attributes, fields


def test_event_log_attributes():
    assert all(
        attribute in attributes(EventLog)
        for attribute in [
            "message_id",
            "name",
            "type",
            "created_at",
            "owner",
            "version",
            "payload",
        ]
    )


def test_event_log_mandatory_attributes():
    assert all(
        fields(EventLog)[field_name].required is True
        for field_name in ["name", "type", "created_at", "owner", "version", "payload"]
    )


def test_event_log_identifier_field_properties():
    identifier_field = fields(EventLog)["message_id"]

    assert isinstance(identifier_field, Auto)
    assert identifier_field.identifier is True
    assert identifier_field.unique is True
