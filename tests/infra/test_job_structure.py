from protean.fields import Auto
from protean.infra.job import Job
from protean.reflection import attributes, fields


def test_event_log_attributes():
    assert all(
        attribute in attributes(Job)
        for attribute in [
            "job_id",
            "type",
            "payload",
            "status",
            "created_at",
            "updated_at",
            "errors",
        ]
    )


def test_job_mandatory_attributes():
    assert all(
        fields(Job)[field_name].required is True for field_name in ["type", "payload"]
    )


def test_event_log_identifier_field_properties():
    identifier_field = fields(Job)["job_id"]

    assert isinstance(identifier_field, Auto)
    assert identifier_field.identifier is True
    assert identifier_field.unique is True
