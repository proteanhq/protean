# --8<-- [start:conftest]
# tests/conftest.py
import pytest
from myapp import domain

# --8<-- [start:import]
from protean.integrations.pytest import DomainFixture

# --8<-- [end:import]


@pytest.fixture(scope="session")
def app_fixture():
    domain.config["event_processing"] = "sync"
    domain.config["command_processing"] = "sync"

    fixture = DomainFixture(domain)
    fixture.setup()
    yield fixture
    fixture.teardown()


@pytest.fixture(autouse=True)
def _ctx(app_fixture):
    with app_fixture.domain_context():
        yield


# --8<-- [end:conftest]


# --8<-- [start:repository_fixtures]
from myapp.models import Order, User


@pytest.fixture
def user_repo():
    return domain.repository_for(User)


@pytest.fixture
def order_repo():
    return domain.repository_for(Order)


# --8<-- [end:repository_fixtures]


# --8<-- [start:repository_usage]
def test_user_is_persisted(user_repo):
    user_repo.add(User(name="Alice", email="alice@example.com"))
    users = user_repo.query.all()
    assert len(users.items) == 1


# --8<-- [end:repository_usage]


# --8<-- [start:global_state]
counter = 0


@pytest.fixture(autouse=True)
def reset_counter():
    global counter
    counter = 0
    yield


# --8<-- [end:global_state]


def test_the_counter_starts_at_zero():
    global counter
    assert counter == 0
    counter += 1


def test_the_counter_is_reset_for_the_next_test():
    assert counter == 0


# --8<-- [start:frozen_clock]
from datetime import UTC, datetime


class FrozenClock:
    """A `Clock` is anything with a `now()` returning an aware UTC datetime."""

    def __init__(self, moment: datetime) -> None:
        self.moment = moment

    def now(self) -> datetime:
        return self.moment


@pytest.fixture
def frozen_clock():
    original = domain.clock
    domain.clock = FrozenClock(datetime(2030, 1, 1, tzinfo=UTC))
    yield domain.clock
    domain.clock = original


# --8<-- [end:frozen_clock]


# --8<-- [start:deadline]
from datetime import timedelta

from protean.utils.eventing import MessageHeaders


def test_a_message_past_its_deadline_is_expired(frozen_clock):
    headers = MessageHeaders(deadline=frozen_clock.now() - timedelta(seconds=1))

    assert headers.is_expired()


def test_time_passing_expires_it(frozen_clock):
    headers = MessageHeaders(deadline=frozen_clock.now() + timedelta(hours=1))
    assert not headers.is_expired()

    frozen_clock.moment += timedelta(hours=2)  # move time, do not wait for it

    assert headers.is_expired()


# --8<-- [end:deadline]
