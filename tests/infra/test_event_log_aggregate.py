import pytest

from protean.infra.eventing import EventLog


@pytest.fixture
def event_log():
    return EventLog(
        name="person_added",
        type="EVENT",
        owner="Test Domain",
        version=1,
        payload={"foo": "bar"},
    )


def test_that_updated_at_is_touched_on_wip_status_change(event_log):
    updated_timestamp = event_log.updated_at

    # Mark as Work in Progress and check for an updated timestamp
    event_log.mark_published()
    assert event_log.updated_at > updated_timestamp


def test_that_updated_at_is_touched_on_consumed_status_change(event_log):
    updated_timestamp = event_log.updated_at

    # Mark as Work in Progress and check for an updated timestamp
    event_log.mark_consumed()
    assert event_log.updated_at > updated_timestamp
