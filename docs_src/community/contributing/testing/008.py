from datetime import UTC, datetime, timedelta


class Retry:
    """Schedules the next attempt of a failed delivery."""

    def __init__(self, delay: timedelta):
        self.delay = delay
        self.scheduled_at: datetime | None = None
        self.next_attempt_at: datetime | None = None

    def schedule(self):
        self.scheduled_at = datetime.now(UTC)
        self.next_attempt_at = self.scheduled_at + self.delay

    def is_due(self):
        return datetime.now(UTC) >= self.next_attempt_at


# --8<-- [start:recorded_time]
def test_scheduling_records_the_next_attempt_one_delay_later():
    retry = Retry(delay=timedelta(minutes=5))

    retry.schedule()

    assert retry.next_attempt_at - retry.scheduled_at == timedelta(minutes=5)


def test_a_retry_is_not_due_before_its_next_attempt():
    retry = Retry(delay=timedelta(minutes=5))

    retry.schedule()

    assert retry.is_due() is False


def test_a_retry_is_due_once_its_next_attempt_has_passed():
    retry = Retry(delay=timedelta(minutes=5))
    retry.schedule()

    retry.next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)

    assert retry.is_due() is True


# --8<-- [end:recorded_time]
