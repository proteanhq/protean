"""An after-commit callback that raises inside a UnitOfWork.

The callback runs once the writes are durable, so its failure is logged and the
commit returns normally: the other callbacks, broker publishing and sync event
dispatch still run. A keyed nested command whose result
``json.dumps`` rejects is the case that reaches this path in practice.
"""

import logging
from datetime import datetime
from typing import Any

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.command import BaseCommand
from protean.core.command_handler import BaseCommandHandler
from protean.core.event import BaseEvent
from protean.core.event_handler import BaseEventHandler
from protean.core.unit_of_work import UnitOfWork, run_after_commit
from protean.exceptions import TransactionError
from protean.fields import Identifier, String
from protean.utils import Processing
from protean.utils.globals import current_domain
from protean.utils.idempotency import IdempotencyStore
from protean.utils.mixins import handle


class DictRedis:
    """The two Redis calls the idempotency store makes, kept in a dict."""

    def __init__(self) -> None:
        self.data: dict[str, Any] = {}

    def get(self, key: str) -> Any:
        return self.data.get(key)

    def setex(self, key: str, ttl: int, value: str) -> None:
        self.data[key] = value


class Opened(BaseEvent):
    account_id: Identifier(required=True)


class Account(BaseAggregate):
    name: String(max_length=50)

    @classmethod
    def open(cls, account_id: str) -> "Account":
        account = cls(id=account_id, name="opened")
        account.raise_(Opened(account_id=account_id))
        return account


class WriteAccount(BaseCommand):
    account_id: Identifier(required=True)


handled_events: list[str] = []


class AccountEvents(BaseEventHandler):
    @handle(Opened)
    def on_opened(self, event: Opened) -> None:
        handled_events.append(event.account_id)


def _circular() -> dict[str, Any]:
    # json.dumps raises ValueError for this value, where a set raises TypeError
    value: dict[str, Any] = {}
    value["self"] = value
    return value


def boom() -> None:
    raise RuntimeError("callback failed")


@pytest.fixture(autouse=True)
def register_accounts(test_domain):
    handled_events.clear()
    test_domain.register(Account)
    test_domain.register(Opened, part_of=Account)
    test_domain.register(WriteAccount, part_of=Account)
    test_domain.register(AccountEvents, part_of=Account)
    test_domain.init(traverse=False)


def _failure_records(caplog) -> list[logging.LogRecord]:
    return [
        r
        for r in caplog.records
        if r.getMessage() == "uow.after_commit_callback_failed"
    ]


class TestCommitAfterAFailingCallback:
    def test_the_commit_returns_and_the_next_callback_runs(self, test_domain, caplog):
        calls = []

        with caplog.at_level(logging.ERROR, logger="protean.core.unit_of_work"):
            with UnitOfWork():
                test_domain.repository_for(Account).add(Account(id="a1", name="x"))
                run_after_commit(boom)
                run_after_commit(lambda: calls.append("ran"))

        assert calls == ["ran"]
        assert test_domain.repository_for(Account).get("a1").name == "x"
        records = _failure_records(caplog)
        assert len(records) == 1
        assert records[0].name == "protean.core.unit_of_work"
        assert records[0].levelno == logging.ERROR
        assert str(records[0].exc_info[1]) == "callback failed"

    def test_the_messages_still_reach_the_broker(self, test_domain):
        with UnitOfWork() as uow:
            uow.register_message("accounts", {"data": "opened"})
            run_after_commit(boom)

        broker = test_domain.brokers["default"]
        messages = broker.read("accounts", "test-group", 10)
        assert [payload for _, payload in messages] == [{"data": "opened"}]

    def test_the_events_are_still_dispatched_under_sync_processing(self, test_domain):
        test_domain.config["event_processing"] = Processing.SYNC.value

        with UnitOfWork():
            test_domain.repository_for(Account).add(Account.open("a1"))
            run_after_commit(boom)

        assert handled_events == ["a1"]

    def test_a_publish_failure_still_fails_the_commit(self, test_domain, monkeypatch):
        def failing_publish(stream: str, message: dict[str, Any]) -> str:
            raise RuntimeError("publish failed")

        monkeypatch.setattr(test_domain.brokers["default"], "publish", failing_publish)

        with pytest.raises(TransactionError, match="publish failed"):
            with UnitOfWork() as uow:
                uow.register_message("accounts", {"data": "opened"})

    def test_a_successful_callback_logs_no_failure(self, test_domain, caplog):
        calls = []

        with caplog.at_level(logging.ERROR, logger="protean.core.unit_of_work"):
            with UnitOfWork():
                run_after_commit(lambda: calls.append("ran"))

        assert calls == ["ran"]
        assert _failure_records(caplog) == []

    def test_a_rollback_discards_the_callback_and_logs_no_failure(
        self, test_domain, caplog
    ):
        with caplog.at_level(logging.ERROR, logger="protean.core.unit_of_work"):
            uow = UnitOfWork()
            uow.start()
            run_after_commit(boom)
            uow.rollback()

        assert _failure_records(caplog) == []

    def test_a_failing_callback_with_no_unit_of_work_still_raises(self, test_domain):
        with pytest.raises(RuntimeError, match="callback failed"):
            run_after_commit(boom)


class TestUnserializableNestedResult:
    @pytest.fixture(autouse=True)
    def fake_redis(self, test_domain):
        self.redis = DictRedis()
        test_domain.idempotency_store._redis = self.redis

        class AccountHandlers(BaseCommandHandler):
            @handle(WriteAccount)
            def write(self, command: WriteAccount) -> set[str]:
                current_domain.repository_for(Account).add(
                    Account.open(command.account_id)
                )
                return {command.account_id}

        test_domain.register(AccountHandlers, part_of=Account)
        test_domain.init(traverse=False)

    def test_the_outer_commit_returns_and_no_key_is_stored(self, test_domain, caplog):
        test_domain.config["event_processing"] = Processing.SYNC.value

        with caplog.at_level(logging.WARNING, logger="protean.utils.idempotency"):
            with UnitOfWork():
                test_domain.process(
                    WriteAccount(account_id="b1"),
                    asynchronous=False,
                    idempotency_key="key-b1",
                )

        assert test_domain.repository_for(Account).get("b1").name == "opened"
        assert handled_events == ["b1"]
        assert self.redis.data == {}
        records = [r for r in caplog.records if "key-b1" in r.getMessage()]
        assert len(records) == 1
        assert records[0].name == "protean.utils.idempotency"
        assert records[0].levelno == logging.WARNING
        assert "not JSON-serializable" in records[0].getMessage()

    def test_a_top_level_command_returns_its_result(self, test_domain):
        result = test_domain.process(
            WriteAccount(account_id="b1"),
            asynchronous=False,
            idempotency_key="key-b1",
        )

        assert result == {"b1"}
        assert self.redis.data == {}


class TestRecordSuccess:
    @pytest.mark.parametrize(
        "result",
        [{1, 2}, datetime(2026, 1, 1), _circular()],
        ids=["set", "datetime", "circular"],
    )
    def test_an_unserializable_result_is_logged_and_not_recorded(self, result, caplog):

        store = IdempotencyStore()
        redis = DictRedis()
        store._redis = redis

        with caplog.at_level(logging.WARNING, logger="protean.utils.idempotency"):
            store.record_success("key-1", result)

        assert redis.data == {}
        records = [r for r in caplog.records if "key-1" in r.getMessage()]
        assert len(records) == 1
        assert "not JSON-serializable" in records[0].getMessage()
        assert records[0].exc_info is not None

    def test_a_serializable_result_is_recorded(self, caplog):
        store = IdempotencyStore()
        redis = DictRedis()
        store._redis = redis

        with caplog.at_level(logging.WARNING, logger="protean.utils.idempotency"):
            store.record_success("key-1", {"id": 1})

        assert caplog.records == []

        assert redis.data == {
            "idempotency:key-1": '{"status": "success", "result": {"id": 1}}'
        }
