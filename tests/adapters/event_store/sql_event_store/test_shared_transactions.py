"""Which transaction a shared store's held messages belong to, and what a
failed commit does with them."""

import threading
from pathlib import Path

import pytest

from protean import Domain
from protean.core.aggregate import BaseAggregate, apply
from protean.core.command import BaseCommand
from protean.core.command_handler import BaseCommandHandler
from protean.core.event import BaseEvent
from protean.core.unit_of_work import UnitOfWork
from protean.exceptions import ExpectedVersionError, TransactionError
from protean.fields import Identifier, String
from protean.utils.globals import current_domain
from protean.utils.mixins import handle

from .conftest import BACKENDS, row_count

# The number of times ``RenameHandler.rename`` ran.
attempts: list[str] = []


class Opened(BaseEvent):
    account_id = Identifier(required=True)


class Renamed(BaseEvent):
    account_id = Identifier(required=True)
    name = String(required=True)


class Account(BaseAggregate):
    name = String()

    @apply
    def on_opened(self, event: Opened) -> None:
        self.id = event.account_id

    @apply
    def on_renamed(self, event: Renamed) -> None:
        self.name = event.name


class Rename(BaseCommand):
    account_id = Identifier(required=True)
    name = String(required=True)


def rename(account_id: str, name: str) -> None:
    repository = current_domain.repository_for(Account)
    account = repository.get(account_id)
    account.raise_(Renamed(account_id=account_id, name=name))
    repository.add(account)


class RenameHandler(BaseCommandHandler):
    @handle(Rename)
    def rename(self, command: Rename) -> None:
        attempts.append(command.name)
        repository = current_domain.repository_for(Account)
        account = repository.get(command.account_id)
        if len(attempts) == 1:
            # Another writer renames the account after this handler loaded
            # it, so the event this handler holds is stale at the commit.
            domain = current_domain._get_current_object()
            writer = threading.Thread(target=rename_elsewhere, args=(domain,))
            writer.start()
            writer.join(timeout=10)
        account.raise_(Renamed(account_id=command.account_id, name=command.name))
        repository.add(account)


def rename_elsewhere(domain: Domain) -> None:
    with domain.domain_context():
        with UnitOfWork():
            rename("a1", "elsewhere")


def register(domain: Domain) -> None:
    domain.register(Account, event_sourced=True)
    domain.register(Opened, part_of=Account)
    domain.register(Renamed, part_of=Account)
    domain.register(Rename, part_of=Account)
    domain.register(RenameHandler, part_of=Account)


def open_account(account_id: str) -> None:
    with UnitOfWork():
        account = Account(id=account_id)
        account.raise_(Opened(account_id=account_id))
        current_domain.repository_for(Account).add(account)


@pytest.mark.no_test_domain
@pytest.mark.parametrize("backend", BACKENDS)
class TestAReusedUnitOfWork:
    def test_the_second_transaction_stores_its_own_message(self, make_shared_domain):
        domain = make_shared_domain()
        store = domain.event_store._require_adapter()
        uow = UnitOfWork()

        uow.start()
        store.write_message("user-1", "Discarded", {})
        uow.rollback()
        uow.start()
        store.write_message("user-1", "Kept", {})
        uow.commit()

        assert [row["type"] for row in store.get_stream_messages("user-1")] == ["Kept"]


@pytest.mark.no_test_domain
@pytest.mark.parametrize("backend", BACKENDS)
class TestACommitAfterAFailedCommit:
    def test_is_refused_and_writes_no_message_twice(self, make_shared_domain):
        domain = make_shared_domain()
        store = domain.event_store._require_adapter()
        uow = UnitOfWork()
        uow.start()
        store.write_message("user-1", "Registered", {})

        def fail() -> None:
            raise RuntimeError("the commit fails after the store wrote")

        # Runs after the store's callback, so the transaction holds the row.
        uow._before_commit.append(fail)
        with pytest.raises(TransactionError, match="the commit fails"):
            uow.commit()
        uow._before_commit.remove(fail)

        with pytest.raises(TransactionError, match="Roll the Unit of Work back"):
            uow.commit()
        uow.rollback()

        assert row_count(domain, "messages") == 0


@pytest.mark.no_test_domain
@pytest.mark.parametrize("backend", BACKENDS)
class TestAWriterThatBypassedTheLock:
    def test_its_row_fails_the_commit_with_an_expected_version_error(
        self, make_shared_domain, monkeypatch
    ):
        domain = make_shared_domain()
        store = domain.event_store._require_adapter()
        assert store.write_message("user-1", "First", {}) == 0
        # The version check reads the stream as empty, as it would before a
        # writer that took no lock inserted its row.
        monkeypatch.setattr(store, "_last_position", lambda conn, stream: -1)

        with pytest.raises(ExpectedVersionError, match="user-1"):
            with UnitOfWork():
                store.write_message("user-1", "Second", {})
                store.write_message("user-2", "Other", {})

        assert row_count(domain, "messages") == 1


@pytest.mark.no_test_domain
@pytest.mark.parametrize("backend", BACKENDS)
class TestASnapshotConflictInsideAUnitOfWork:
    def test_raises_at_the_write_and_rolls_back(self, make_shared_domain):
        domain = make_shared_domain()
        store = domain.event_store._require_adapter()
        stream = "shared0::account:snapshot-a1"

        with pytest.raises(ExpectedVersionError, match="snapshot-a1"):
            with UnitOfWork():
                store.write_message("user-1", "Registered", {})
                store.write_message(stream, "SNAPSHOT", {}, expected_version=3)

        assert row_count(domain, "messages") == 0
        assert store.get_last_stream_message(stream) is None


@pytest.mark.sqlite
@pytest.mark.no_test_domain
class TestAStoreOfAnotherDomain:
    """Domain ``a`` and domain ``b`` each share their own SQLite file."""

    @pytest.fixture
    def backend(self) -> str:
        return "sqlite"

    @pytest.fixture
    def domains(self, make_shared_domain, tmp_path: Path) -> tuple[Domain, Domain]:
        a = make_shared_domain()
        b = make_shared_domain(
            databases={
                "default": {
                    "provider": "sqlite",
                    "database_uri": f"sqlite:///{tmp_path / 'b.db'}",
                }
            }
        )
        return a, b

    def test_writes_at_once_inside_a_unit_of_work_of_this_domain(self, domains):
        a, b = domains
        b_store = b.event_store._require_adapter()
        assert b_store.write_message("user-1", "Registered", {}) == 0

        with a.domain_context():
            with UnitOfWork():
                assert b_store.write_message("user-1", "Renamed", {}) == 1
                rows = b_store.get_stream_messages("user-1")

        assert [row["type"] for row in rows] == ["Registered", "Renamed"]
        assert row_count(a, "messages") == 0
        assert row_count(b, "messages") == 2

    def test_writes_at_once_when_its_context_is_pushed_inside(self, domains):
        a, b = domains

        with a.domain_context():
            with UnitOfWork():
                with b.domain_context():
                    position = b.event_store._require_adapter().write_message(
                        "user-1", "Registered", {}
                    )

        assert position == 0
        assert row_count(a, "messages") == 0
        assert row_count(b, "messages") == 1


@pytest.mark.postgresql
@pytest.mark.no_test_domain
class TestAStaleHeldEvent:
    @pytest.fixture
    def backend(self) -> str:
        return "postgresql"

    def test_fails_the_commit_and_the_version_retry_reruns_the_handler(
        self, make_shared_domain
    ):
        attempts.clear()
        domain = make_shared_domain(register)
        open_account("a1")

        domain.process(Rename(account_id="a1", name="here"))

        assert attempts == ["here", "here"]
        rows = domain.event_store._require_adapter().get_stream_messages(
            "shared0::account-a1"
        )
        assert [(row["type"].split(".")[-2], row["position"]) for row in rows] == [
            ("Opened", 0),
            ("Renamed", 1),
            ("Renamed", 2),
        ]
        assert [row["data"]["name"] for row in rows[1:]] == ["elsewhere", "here"]
