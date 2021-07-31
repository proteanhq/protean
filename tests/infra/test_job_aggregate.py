import pytest

from protean.infra.job import Job, JobTypes


@pytest.fixture
def job():
    return Job(type=JobTypes.SUBSCRIPTION.value, payload={"foo": "bar"})


def test_that_updated_at_is_touched_on_wip_status_change(job):
    updated_timestamp = job.updated_at

    # Mark as Work in Progress and check for an updated timestamp
    job.mark_in_progress()
    assert job.updated_at > updated_timestamp


def test_that_updated_at_is_touched_on_consumed_status_change(job):
    updated_timestamp = job.updated_at

    # Mark as Work in Progress and check for an updated timestamp
    job.mark_completed()
    assert job.updated_at > updated_timestamp


def test_that_updated_at_is_touched_on_errored_status_change(job):
    updated_timestamp = job.updated_at

    # Mark as Work in Progress and check for an updated timestamp
    job.mark_errored()
    assert job.updated_at > updated_timestamp
