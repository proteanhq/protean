"""Check what docs/guides/change-state/event-store-setup.md says.

The page's example runs on the default memory event store. Each test loads the
example fresh and writes account ``acc-001`` itself: an ``AccountOpened`` event
at position 0, then one ``Deposited`` event per deposit.
"""

from datetime import UTC, datetime

import pytest

from protean.exceptions import ObjectNotFoundError
from tests.docs.support import load_example

pytestmark = pytest.mark.no_test_domain

DEPOSITS = (10.0, 20.0, 30.0, 40.0, 50.0, 60.0)


class FixedClock:
    """A clock that returns the time it was given, through ``domain.clock``."""

    def __init__(self, now: datetime):
        self._now = now

    def now(self) -> datetime:
        return self._now


@pytest.fixture
def example():
    module = load_example("guides/change-state/event-store-setup/001.py")
    module.domain.init(traverse=False)
    with module.domain.domain_context():
        yield module
    module.domain.event_store.store._data_reset()


def open_account(example, deposits):
    account = example.Account.open("acc-001")
    for amount in deposits:
        account.deposit(amount)
    example.domain.repository_for(example.Account).add(account)


def test_the_example_uses_the_memory_event_store(example):
    assert example.domain.config["event_store"]["provider"] == "memory"


def test_read_returns_the_appended_events_with_their_payloads(example):
    open_account(example, DEPOSITS)

    messages, _, _, _ = example.read_account_events()

    assert len(messages) == 7
    assert messages[0].metadata.headers.type == "Myapp.AccountOpened.v1"
    assert messages[0].data == {"account_id": "acc-001"}
    assert messages[1].metadata.headers.type == "Myapp.Deposited.v1"
    assert messages[1].data == {"amount": 10.0}
    assert [message.data["amount"] for message in messages[1:]] == list(DEPOSITS)


def test_read_finds_nothing_before_the_account_is_written(example):
    messages, later, last, deposited = example.read_account_events()

    assert messages == []
    assert later == []
    assert last is None
    assert deposited == 0.0


def test_read_from_a_position_skips_the_earlier_events(example):
    open_account(example, DEPOSITS)

    _, later, _, _ = example.read_account_events()

    # Positions 5 and 6 hold the last two deposits.
    assert [message.data["amount"] for message in later] == [50.0, 60.0]


def test_read_last_message_returns_the_latest_event(example):
    open_account(example, DEPOSITS)

    _, _, last, _ = example.read_account_events()

    assert last.metadata.headers.type == "Myapp.Deposited.v1"
    assert last.data == {"amount": 60.0}


def test_read_all_pages_through_the_whole_category(example):
    open_account(example, DEPOSITS)

    _, _, _, deposited = example.read_account_events()

    assert deposited == sum(DEPOSITS)


def test_the_account_replays_from_its_events(example):
    open_account(example, DEPOSITS)

    account = example.domain.repository_for(example.Account).get("acc-001")

    assert account.id == "acc-001"
    assert account.balance == sum(DEPOSITS)
    assert account._version == 6


def test_temporal_queries_load_the_account_at_a_version_and_a_time(example):
    repo = example.domain.repository_for(example.Account)

    # Two deposits before noon on 15 June 2024, four after it.
    example.domain.clock = FixedClock(datetime(2024, 6, 15, 11, 0, tzinfo=UTC))
    open_account(example, DEPOSITS[:2])
    example.domain.clock = FixedClock(datetime(2024, 6, 15, 13, 0, tzinfo=UTC))
    account = repo.get("acc-001")
    for amount in DEPOSITS[2:]:
        account.deposit(amount)
    repo.add(account)

    at_version, as_of = example.account_history("acc-001")

    assert at_version._version == 5
    assert at_version.balance == sum(DEPOSITS[:5])
    assert as_of._version == 2
    assert as_of.balance == sum(DEPOSITS[:2])


def test_temporal_query_fails_when_no_event_is_that_old(example):
    open_account(example, DEPOSITS)  # written now, long after June 2024

    with pytest.raises(ObjectNotFoundError, match="no events on or before"):
        example.account_history("acc-001")
