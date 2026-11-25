"""Reads and snapshot writes of a store that shares ``default``.

Inside a Unit of Work they run on its connection. Outside one, a read runs on
a connection of its own and returns it to the pool.
"""

import pytest

import protean.adapters.event_store.sql.store as sql_store
from protean import Domain
from protean.core.aggregate import BaseAggregate, apply
from protean.core.event import BaseEvent
from protean.core.unit_of_work import UnitOfWork
from protean.fields import Identifier, String
from protean.utils.globals import current_domain
from tests.shared import provider_adapter

from .conftest import BACKENDS, row_count


class Opened(BaseEvent):
    account_id = Identifier(required=True)


class Account(BaseAggregate):
    name = String()

    @apply
    def on_opened(self, event: Opened) -> None:
        self.id = event.account_id


class Invoice(BaseAggregate):
    number = String()


def register(domain: Domain) -> None:
    domain.register(Account, event_sourced=True)
    domain.register(Opened, part_of=Account)
    domain.register(Invoice)


def open_account(account_id: str) -> None:
    with UnitOfWork():
        account = Account(id=account_id)
        account.raise_(Opened(account_id=account_id))
        current_domain.repository_for(Account).add(account)


@pytest.mark.sqlite
@pytest.mark.no_test_domain
class TestALoadAfterAWriteOnSqlite:
    @pytest.fixture
    def backend(self) -> str:
        return "sqlite"

    def test_the_load_reads_on_the_unit_of_work_connection(
        self, make_shared_domain, monkeypatch
    ):
        # A read on a second connection would wait for the write lock the Unit
        # of Work holds, and fail once this timeout ends.
        monkeypatch.setattr(sql_store, "_SQLITE_BUSY_TIMEOUT_MS", 100)
        domain = make_shared_domain(register)
        with provider_adapter(domain, "default")._engine.connect() as conn:
            assert conn.exec_driver_sql("PRAGMA busy_timeout").scalar() == 100
        open_account("a1")

        with UnitOfWork() as uow:
            current_domain.repository_for(Invoice).add(Invoice(number="1"))
            uow._sessions["default"].flush()
            account = current_domain.repository_for(Account).get("a1")

        assert account.id == "a1"
        assert row_count(domain, "invoice") == 1


@pytest.mark.no_test_domain
@pytest.mark.parametrize("backend", BACKENDS)
class TestReadsOfASharedStore:
    @pytest.fixture
    def domain(self, make_shared_domain) -> Domain:
        return make_shared_domain(register)

    def test_a_read_inside_sees_the_snapshot_written_inside(self, domain):
        store = domain.event_store._require_adapter()
        stream = "shared0::account:snapshot-a1"

        with UnitOfWork():
            store.write_message(stream, "SNAPSHOT", {"name": "a"})
            snapshot = store.get_last_stream_message(stream)
            assert snapshot is not None
            assert snapshot["data"] == {"name": "a"}

        assert store.get_last_stream_message(stream) is not None

    def test_a_read_inside_does_not_see_a_held_message(self, domain):
        store = domain.event_store._require_adapter()

        with UnitOfWork():
            assert store.write_message("user-1", "Registered", {}) is None
            assert store.get_stream_messages("user-1") == []

        assert [row["type"] for row in store.get_stream_messages("user-1")] == [
            "Registered"
        ]

    def test_a_read_outside_returns_its_connection(self, domain):
        store = domain.event_store._require_adapter()
        assert store.write_message("user-1", "Registered", {}) == 0
        pool = provider_adapter(domain, "default")._engine.pool

        rows = store.get_stream_messages("user-1")

        assert [row["position"] for row in rows] == [0]
        assert pool.checkedout() == 0

    def test_a_snapshot_written_inside_rolls_back_with_it(self, domain):
        store = domain.event_store._require_adapter()
        stream = "shared0::account:snapshot-a1"

        with pytest.raises(RuntimeError, match="rolled back"):
            with UnitOfWork():
                store.write_message(stream, "SNAPSHOT", {"name": "a"})
                raise RuntimeError("rolled back")

        assert store.get_last_stream_message(stream) is None

    def test_two_messages_on_one_stream_take_consecutive_positions(self, domain):
        store = domain.event_store._require_adapter()

        with UnitOfWork():
            store.write_message("user-1", "Registered", {}, expected_version=-1)
            store.write_message("user-1", "Renamed", {}, expected_version=0)

        rows = store.get_stream_messages("user-1")
        assert [(row["type"], row["position"]) for row in rows] == [
            ("Registered", 0),
            ("Renamed", 1),
        ]
