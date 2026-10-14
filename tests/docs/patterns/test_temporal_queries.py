"""Run the examples on ``docs/patterns/temporal-queries.md``.

Each test loads the example fresh and writes the page's account history with
``record_account_history``: ``acct-1001`` is opened (v0) and verified (v1) in
the first save, gets two limit raises (v2, v3) in the second, and is
suspended (v4) in the third.
"""

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from protean.exceptions import IncorrectUsageError, ObjectNotFoundError
from tests.docs.support import load_example

pytestmark = pytest.mark.no_test_domain

STREAM = "compliance::account-acct-1001"


@pytest.fixture
def example():
    module = load_example("patterns/temporal-queries/001.py")
    with module.compliance.domain_context():
        module.record_account_history()
        yield module
        module.compliance.event_store.store._data_reset()


@pytest.fixture
def repo(example):
    return example.compliance.repository_for(example.Account)


@pytest.fixture
def write_times(example):
    """The write time of each stored event, in version order.

    These are the timestamps ``as_of`` compares against.
    """
    rows = example.compliance.event_store.store._read(STREAM)
    assert [row["position"] for row in rows] == [0, 1, 2, 3, 4]
    return [datetime.fromisoformat(row["time"]) for row in rows]


# --- at_version ---------------------------------------------------------------


def test_page_at_version_example_runs(example):
    example.inspect_account_at_version_1()


def test_current_state_is_the_last_event(repo):
    account = repo.get("acct-1001")

    assert account._version == 4
    assert account.status == "suspended"
    assert account.verification_status == "suspended"
    assert account.suspension_reason == "Suspicious activity"
    assert account.daily_transaction_limit == 100_000.00
    assert account._is_temporal is False


def test_at_version_1_is_verified_with_the_default_limit(repo):
    account = repo.get("acct-1001", at_version=1)

    assert account._version == 1
    assert account.verification_status == "verified"
    assert account.verification_level == "full"
    assert account.daily_transaction_limit == 1000.00
    assert account.status == "active"
    assert account._is_temporal is True


def test_at_version_1_differs_from_the_current_state(repo):
    past = repo.get("acct-1001", at_version=1)
    now = repo.get("acct-1001")

    assert past.status != now.status
    assert past.daily_transaction_limit != now.daily_transaction_limit


@pytest.mark.parametrize(
    ("version", "limit", "status"),
    [
        (0, 1000.00, "unverified"),
        (2, 50_000.00, "verified"),
        (3, 100_000.00, "verified"),
        (4, 100_000.00, "suspended"),
    ],
)
def test_each_version_shows_the_state_after_that_event(repo, version, limit, status):
    account = repo.get("acct-1001", at_version=version)

    assert account._version == version
    assert account.daily_transaction_limit == limit
    assert account.verification_status == status


def test_at_version_past_the_latest_is_not_found(repo):
    with pytest.raises(ObjectNotFoundError):
        repo.get("acct-1001", at_version=5)


# --- as_of --------------------------------------------------------------------


def test_as_of_a_write_time_includes_that_event(example, write_times):
    account = example.account_at_quarter_end(write_times[1])

    assert account._version == 1
    assert account.verification_status == "verified"
    assert account.daily_transaction_limit == 1000.00
    assert account._is_temporal is True


def test_as_of_just_before_a_write_excludes_that_event(example, write_times):
    assert write_times[1] < write_times[2]  # each event has its own write time

    before_limit_raise = write_times[2] - timedelta(microseconds=1)
    account = example.account_at_quarter_end(before_limit_raise)

    assert account._version == 1
    assert account.daily_transaction_limit == 1000.00


def test_as_of_after_the_limit_raises_shows_the_raised_limit(example, write_times):
    account = example.account_at_quarter_end(write_times[3])

    assert account._version == 3
    assert account.daily_transaction_limit == 100_000.00
    assert account.status == "active"


def test_as_of_the_last_write_matches_the_current_state(example, repo, write_times):
    account = example.account_at_quarter_end(write_times[4])

    assert account._version == repo.get("acct-1001")._version == 4
    assert account.status == "suspended"


def test_as_of_before_the_first_event_is_not_found(example, write_times):
    with pytest.raises(ObjectNotFoundError, match="has no events on or before"):
        example.account_at_quarter_end(write_times[0] - timedelta(seconds=1))


def test_as_of_prints_the_reported_state(example, write_times, capsys):
    example.account_at_quarter_end(write_times[3])

    assert capsys.readouterr().out.splitlines() == [
        "Verification: verified",
        "Limit: 100000.0",
        "Version at that time: 3",
    ]


def test_at_version_and_as_of_together_are_rejected(repo, write_times):
    assert repo.get("acct-1001", at_version=1)._version == 1

    with pytest.raises(IncorrectUsageError, match="mutually exclusive"):
        repo.get("acct-1001", at_version=1, as_of=write_times[1])


# --- application service and API ----------------------------------------------


def test_audit_service_reads_a_past_version(example):
    account = example.AccountAuditService().get_account_at_version("acct-1001", 2)

    assert account._version == 2
    assert account.daily_transaction_limit == 50_000.00


def test_audit_service_reads_as_of_a_time(example, write_times):
    account = example.AccountAuditService().get_account_as_of(
        "acct-1001", write_times[0]
    )

    assert account._version == 0
    assert account.verification_status == "unverified"


def test_compare_lists_only_the_fields_that_changed(example):
    result = example.AccountAuditService().compare_account_versions("acct-1001", 1, 3)

    assert result["changes"]["daily_transaction_limit"] == {
        "version_a": 1000.00,
        "version_b": 100_000.00,
    }
    assert "holder_name" not in result["changes"]
    assert "verification_status" not in result["changes"]


def test_compare_of_a_version_with_itself_finds_no_changes(example):
    result = example.AccountAuditService().compare_account_versions("acct-1001", 2, 2)

    assert result["changes"] == {}


@pytest.fixture
def api():
    """A client for the page's app, with no domain context open around it.

    The app's ``DomainContextMiddleware`` has to supply the context, as it does
    in production. The write times are read while the history is written.
    """
    module = load_example("patterns/temporal-queries/001.py")
    with module.compliance.domain_context():
        module.record_account_history()
        rows = module.compliance.event_store.store._read(STREAM)
        times = [datetime.fromisoformat(row["time"]) for row in rows]
    assert len(times) == 5
    yield TestClient(module.app), times
    with module.compliance.domain_context():
        module.compliance.event_store.store._data_reset()


def test_api_returns_the_account_at_a_version(api):
    client, _ = api
    response = client.get("/accounts/acct-1001/at-version/2")

    assert response.status_code == 200
    assert response.json() == {
        "account_id": "acct-1001",
        "verification_status": "verified",
        "daily_transaction_limit": 50_000.00,
        "version": 2,
        "is_temporal": True,
    }


def test_api_returns_the_account_as_of_a_time(api):
    client, times = api
    response = client.get(
        "/accounts/acct-1001/as-of", params={"timestamp": times[3].isoformat()}
    )

    assert response.status_code == 200
    assert response.json()["version"] == 3
    assert response.json()["daily_transaction_limit"] == 100_000.00


def test_api_returns_404_for_an_unknown_account(api):
    client, _ = api
    response = client.get("/accounts/acct-9999/at-version/0")

    assert response.status_code == 404


def test_api_returns_404_before_the_first_event(api):
    client, times = api
    early = (times[0] - timedelta(seconds=1)).isoformat()
    response = client.get("/accounts/acct-1001/as-of", params={"timestamp": early})

    assert response.status_code == 404


def test_api_returns_422_for_a_timestamp_that_is_not_iso_8601(api):
    client, _ = api
    response = client.get("/accounts/acct-1001/as-of", params={"timestamp": "garbage"})

    assert response.status_code == 422


# --- read-only safety ---------------------------------------------------------


def test_page_read_only_example_prints_the_rejection(example, capsys):
    example.try_to_change_a_past_version()

    assert capsys.readouterr().out.strip() == (
        "Cannot raise events on a temporally-loaded aggregate. "
        "Temporal aggregates are read-only."
    )


def test_raise_on_a_temporal_aggregate_is_rejected(repo):
    account_v1 = repo.get("acct-1001", at_version=1)

    with pytest.raises(IncorrectUsageError, match="read-only"):
        account_v1.change_transaction_limit(999_999.00, "Attempted fraud")
    assert account_v1.daily_transaction_limit == 1000.00
    assert account_v1._events == []


def test_raise_on_a_current_aggregate_records_the_event(example, repo):
    account = repo.get("acct-1001")

    account.change_transaction_limit(5_000.00, "Lowered after review")

    assert account.daily_transaction_limit == 5_000.00
    assert [type(e) for e in account._events] == [example.TransactionLimitChanged]


def test_setting_an_attribute_on_a_temporal_aggregate_is_never_saved(repo):
    account_v1 = repo.get("acct-1001", at_version=1)

    account_v1.daily_transaction_limit = 999_999.00
    repo.add(account_v1)

    assert repo.get("acct-1001")._version == 4
    assert repo.get("acct-1001").daily_transaction_limit == 100_000.00


# --- identity map -------------------------------------------------------------


def test_page_identity_map_example_runs(example):
    example.load_current_and_past_in_one_unit_of_work()


def test_temporal_get_is_a_new_object_each_time(repo):
    first = repo.get("acct-1001", at_version=1)
    second = repo.get("acct-1001", at_version=1)

    assert first is not second
    assert first._version == second._version == 1


# --- restoring a limit --------------------------------------------------------


def test_restore_adds_a_new_event_with_the_old_limit(example, repo):
    example.restore_transaction_limit("acct-1001", version=1)

    account = repo.get("acct-1001")
    assert account._version == 5
    assert account.daily_transaction_limit == 1000.00
    # History is kept: version 3 still shows the raised limit.
    assert repo.get("acct-1001", at_version=3).daily_transaction_limit == 100_000.00


def test_restore_to_the_current_limit_changes_nothing_visible(example, repo):
    example.restore_transaction_limit("acct-1001", version=4)

    account = repo.get("acct-1001")
    assert account._version == 5
    assert account.daily_transaction_limit == 100_000.00
