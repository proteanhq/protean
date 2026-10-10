"""Check what docs/guides/change-state/snapshots.md says about snapshots.

The page's example builds an event-sourced ``Account`` with one account,
``acc-001``, holding three events, then snapshots it by hand. Each test loads
the example fresh, so every test gets its own domain and its own memory event
store.
"""

import pytest

from tests.docs.support import load_example

pytestmark = pytest.mark.no_test_domain


@pytest.fixture
def example():
    module = load_example("guides/change-state/snapshots/001.py")
    yield module
    module.domain.event_store.store._data_reset()


def last_snapshot(module, identifier):
    """Return the newest row in the account's snapshot stream, or None."""
    category = module.Account.meta_.stream_category
    return module.domain.event_store.store._read_last_message(
        f"{category}:snapshot-{identifier}"
    )


def snapshot_rows(module, identifier):
    """Return every row in the account's snapshot stream, oldest first."""
    category = module.Account.meta_.stream_category
    return module.domain.event_store.store._read(f"{category}:snapshot-{identifier}")


def write_account(module, identifier, deposits):
    """Open an account and add ``deposits`` deposits of 10.0 in one write.

    Nothing loads the account here, so no automatic snapshot can be taken.
    """
    account = module.Account.open(identifier, holder="Bob")
    for _ in range(deposits):
        account.deposit(10.0)
    module.domain.repository_for(module.Account).add(account)


def test_default_threshold_is_ten_events(example):
    assert example.domain.config["snapshot_threshold"] == 10


def test_manual_snapshot_stores_the_account_state(example):
    with example.domain.domain_context():
        snapshot = last_snapshot(example, "acc-001")

        assert snapshot is not None
        assert snapshot["data"]["account_id"] == "acc-001"
        assert snapshot["data"]["holder"] == "Alice"
        assert snapshot["data"]["balance"] == 150.0
        assert snapshot["data"]["_version"] == 2


def test_each_manual_call_writes_a_snapshot_of_acc_001(example):
    # create_snapshot, create_snapshots and create_all_snapshots each wrote one.
    with example.domain.domain_context():
        rows = snapshot_rows(example, "acc-001")

    assert len(rows) == 3
    assert all(row["data"]["balance"] == 150.0 for row in rows)


def test_create_snapshot_returns_true(example):
    with example.domain.domain_context():
        assert example.domain.create_snapshot(example.Account, "acc-001") is True


def test_create_snapshots_returns_the_number_of_instances(example):
    # The example's own loops saw one account.
    assert example.results == {"Account": 1}

    with example.domain.domain_context():
        write_account(example, "acc-002", deposits=1)

        assert example.domain.create_snapshots(example.Account) == 2
        assert example.domain.create_all_snapshots() == {"Account": 2}
        assert last_snapshot(example, "acc-002")["data"]["balance"] == 10.0


def test_load_creates_a_snapshot_once_events_reach_the_threshold(example):
    with example.domain.domain_context():
        # One opening event and nine deposits: ten events, the default threshold.
        write_account(example, "acc-auto", deposits=9)
        assert last_snapshot(example, "acc-auto") is None

        loaded = example.domain.repository_for(example.Account).get("acc-auto")

        snapshot = last_snapshot(example, "acc-auto")
        assert snapshot is not None
        assert snapshot["data"]["balance"] == 90.0
        assert snapshot["data"]["_version"] == 9
        assert loaded.balance == 90.0


def test_load_creates_no_snapshot_below_the_threshold(example):
    with example.domain.domain_context():
        # One opening event and eight deposits: nine events, one short.
        write_account(example, "acc-short", deposits=8)

        loaded = example.domain.repository_for(example.Account).get("acc-short")

        assert loaded.balance == 80.0
        assert last_snapshot(example, "acc-short") is None


def test_load_from_a_snapshot_applies_the_later_events(example):
    with example.domain.domain_context():
        repo = example.domain.repository_for(example.Account)

        # The example's snapshot of acc-001 is at version 2, balance 150.0.
        account = repo.get("acc-001")
        account.deposit(25.0)
        repo.add(account)

        loaded = repo.get("acc-001")

        assert last_snapshot(example, "acc-001")["data"]["_version"] == 2
        assert loaded.holder == "Alice"
        assert loaded.balance == 175.0
        assert loaded._version == 3


def test_load_starts_from_the_snapshot_not_from_the_first_event(example):
    with example.domain.domain_context():
        # A snapshot whose balance no replay of acc-001's events can produce.
        # Loading returns it only if the repository starts from the snapshot.
        category = example.Account.meta_.stream_category
        data = dict(last_snapshot(example, "acc-001")["data"], balance=999.0)
        example.domain.event_store.store._write(
            f"{category}:snapshot-acc-001", "SNAPSHOT", data
        )

        loaded = example.domain.repository_for(example.Account).get("acc-001")

        assert loaded.balance == 999.0
        assert loaded._version == 2
