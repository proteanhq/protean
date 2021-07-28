from protean.core.field.basic import Auto
from protean.infra.job import Job


def test_event_log_attributes():
    assert all(
        attribute in Job.meta_.attributes
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
        Job.meta_.declared_fields[field_name].required is True
        for field_name in ["type", "payload"]
    )


def test_event_log_identifier_field_properties():
    identifier_field = Job.meta_.declared_fields["job_id"]

    assert isinstance(identifier_field, Auto)
    assert identifier_field.identifier is True
    assert identifier_field.unique is True
