"""Work deferred until the outermost UnitOfWork's writes are durable.

A command processed synchronously inside an outer UnitOfWork records its
idempotency key this way. If a later failure rolls the outer transaction back,
the command's write is gone, so its key must not be recorded either: the outer
handler's retry has to run the command again.
"""

from typing import Any
from unittest.mock import patch

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.command import BaseCommand
from protean.core.command_handler import BaseCommandHandler
from protean.core.unit_of_work import UnitOfWork, run_after_commit
from protean.exceptions import DuplicateCommandError, ExpectedVersionError
from protean.fields import Identifier, String
from protean.utils.globals import current_domain
from protean.utils.mixins import handle


class DictRedis:
    """The two Redis calls the idempotency store makes, kept in a dict."""

    def __init__(self) -> None:
        self.data: dict[str, Any] = {}

    def get(self, key: str) -> Any:
        return self.data.get(key)

    def setex(self, key: str, ttl: int, value: str) -> None:
        self.data[key] = value


def test_runs_at_once_with_no_unit_of_work_active(test_domain):
    calls = []

    run_after_commit(lambda: calls.append("ran"))

    assert calls == ["ran"]


def test_waits_for_the_commit(test_domain):
    calls = []

    with UnitOfWork():
        run_after_commit(lambda: calls.append("ran"))
        assert calls == []

    assert calls == ["ran"]


def test_is_dropped_on_rollback(test_domain):
    calls = []

    with pytest.raises(RuntimeError):
        with UnitOfWork():
            run_after_commit(lambda: calls.append("ran"))
            raise RuntimeError("boom")

    assert calls == []


def test_inside_a_nested_unit_of_work_waits_for_the_outermost_commit(test_domain):
    calls = []

    with UnitOfWork():
        with UnitOfWork():
            run_after_commit(lambda: calls.append("ran"))
        assert calls == []

    assert calls == ["ran"]


class Account(BaseAggregate):
    name: String(max_length=50)


class OpenAccount(BaseCommand):
    account_id: Identifier(required=True)


class WriteAccount(BaseCommand):
    account_id: Identifier(required=True)


class CloseAccount(BaseCommand):
    account_id: Identifier(required=True)


class TestNestedCommandIdempotency:
    @pytest.fixture(autouse=True)
    def register_accounts(self, test_domain):
        test_domain.register(Account)
        test_domain.register(OpenAccount, part_of=Account)
        test_domain.register(WriteAccount, part_of=Account)
        test_domain.register(CloseAccount, part_of=Account)
        self.redis = DictRedis()
        test_domain.idempotency_store._redis = self.redis

    @patch("protean.utils.mixins.time.sleep")
    def test_a_keyed_nested_command_runs_again_when_the_outer_handler_retries(
        self, mock_sleep, test_domain
    ):
        runs = {"open": 0, "write": 0, "close": 0}

        class AccountHandlers(BaseCommandHandler):
            @handle(OpenAccount)
            def open(self, command: OpenAccount) -> None:
                runs["open"] += 1
                current_domain.process(
                    WriteAccount(account_id="b1"),
                    asynchronous=False,
                    idempotency_key="key-b1",
                )
                current_domain.process(
                    CloseAccount(account_id="c1"), asynchronous=False
                )

            @handle(WriteAccount)
            def write(self, command: WriteAccount) -> None:
                runs["write"] += 1
                current_domain.repository_for(Account).add(
                    Account(id=command.account_id, name="written")
                )

            @handle(CloseAccount)
            def close(self, command: CloseAccount) -> None:
                runs["close"] += 1
                if runs["close"] == 1:
                    raise ExpectedVersionError("stale")
                current_domain.repository_for(Account).add(
                    Account(id=command.account_id, name="closed")
                )

        test_domain.register(AccountHandlers, part_of=Account)
        test_domain.init(traverse=False)

        test_domain.process(OpenAccount(account_id="a1"), asynchronous=False)

        assert runs == {"open": 2, "write": 2, "close": 2}
        repo = test_domain.repository_for(Account)
        assert repo.get_or_none("b1") is not None
        assert repo.get_or_none("c1") is not None
        assert "idempotency:key-b1" in self.redis.data

    def test_a_keyed_nested_command_is_not_recorded_when_the_outer_work_rolls_back(
        self, test_domain
    ):
        class AccountHandlers(BaseCommandHandler):
            @handle(WriteAccount)
            def write(self, command: WriteAccount) -> None:
                current_domain.repository_for(Account).add(
                    Account(id=command.account_id, name="written")
                )

        test_domain.register(AccountHandlers, part_of=Account)
        test_domain.init(traverse=False)

        with pytest.raises(RuntimeError):
            with UnitOfWork():
                test_domain.process(
                    WriteAccount(account_id="b1"),
                    asynchronous=False,
                    idempotency_key="key-b1",
                )
                raise RuntimeError("boom")

        assert self.redis.data == {}
        assert test_domain.repository_for(Account).get_or_none("b1") is None

    def test_a_keyed_top_level_command_is_recorded(self, test_domain):
        class AccountHandlers(BaseCommandHandler):
            @handle(WriteAccount)
            def write(self, command: WriteAccount) -> None:
                current_domain.repository_for(Account).add(
                    Account(id=command.account_id, name="written")
                )

        test_domain.register(AccountHandlers, part_of=Account)
        test_domain.init(traverse=False)

        test_domain.process(
            WriteAccount(account_id="b1"),
            asynchronous=False,
            idempotency_key="key-b1",
        )

        assert "idempotency:key-b1" in self.redis.data

    def _register_counting_writer(self, test_domain):
        runs = []

        class AccountHandlers(BaseCommandHandler):
            @handle(WriteAccount)
            def write(self, command: WriteAccount) -> str:
                runs.append(command.account_id)
                current_domain.repository_for(Account).add(
                    Account(id=command.account_id, name="written")
                )
                return command.account_id

        test_domain.register(AccountHandlers, part_of=Account)
        test_domain.init(traverse=False)
        return runs

    def test_a_repeated_key_in_one_transaction_runs_the_command_once(self, test_domain):
        runs = self._register_counting_writer(test_domain)

        with UnitOfWork():
            first = test_domain.process(
                WriteAccount(account_id="b1"),
                asynchronous=False,
                idempotency_key="key-b1",
            )
            second = test_domain.process(
                WriteAccount(account_id="b1"),
                asynchronous=False,
                idempotency_key="key-b1",
            )

        assert runs == ["b1"]
        assert first == second == "b1"

    def test_a_repeated_key_in_one_transaction_raises_when_asked(self, test_domain):
        self._register_counting_writer(test_domain)

        with pytest.raises(DuplicateCommandError) as exc_info:
            with UnitOfWork():
                test_domain.process(
                    WriteAccount(account_id="b1"),
                    asynchronous=False,
                    idempotency_key="key-b1",
                )
                test_domain.process(
                    WriteAccount(account_id="b1"),
                    asynchronous=False,
                    idempotency_key="key-b1",
                    raise_on_duplicate=True,
                )

        assert exc_info.value.original_result == "b1"

    def test_a_rolled_back_key_does_not_carry_into_the_next_transaction(
        self, test_domain
    ):
        runs = self._register_counting_writer(test_domain)
        uow = UnitOfWork()

        with pytest.raises(RuntimeError):
            with uow:
                test_domain.process(
                    WriteAccount(account_id="b1"),
                    asynchronous=False,
                    idempotency_key="key-b1",
                )
                raise RuntimeError("boom")

        with uow:
            test_domain.process(
                WriteAccount(account_id="b1"),
                asynchronous=False,
                idempotency_key="key-b1",
            )

        assert runs == ["b1", "b1"]
        assert "idempotency:key-b1" in self.redis.data
