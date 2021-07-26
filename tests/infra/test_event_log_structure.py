from protean.core.field.basic import Auto
from protean.infra.eventing import EventLog


def test_event_log_attributes():
    assert all(
        attribute in EventLog.meta_.attributes
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
        EventLog.meta_.declared_fields[field_name].required is True
        for field_name in ["name", "type", "created_at", "owner", "version", "payload"]
    )


def test_event_log_identifier_field_properties():
    identifier_field = EventLog.meta_.declared_fields["message_id"]

    assert isinstance(identifier_field, Auto)
    assert identifier_field.identifier is True
    assert identifier_field.unique is True
