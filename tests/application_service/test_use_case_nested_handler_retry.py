"""A command handler called from a ``@use_case`` runs inside the use case's
UnitOfWork, so it does not retry a version conflict in place. The use case
has no retry of its own, so its caller receives the conflict."""

from unittest.mock import patch

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.application_service import BaseApplicationService, use_case
from protean.core.command import BaseCommand
from protean.core.command_handler import BaseCommandHandler
from protean.exceptions import ExpectedVersionError
from protean.fields import Identifier, String
from protean.utils.globals import current_domain
from protean.utils.mixins import handle


class Account(BaseAggregate):
    name: String(max_length=50)


class WriteAccount(BaseCommand):
    account_id: Identifier(required=True)


inner_runs = 0


class AccountHandlers(BaseCommandHandler):
    @handle(WriteAccount)
    def write(self, command: WriteAccount) -> None:
        global inner_runs
        inner_runs += 1
        if inner_runs == 1:
            raise ExpectedVersionError("stale")
        current_domain.repository_for(Account).add(
            Account(id=command.account_id, name="written")
        )


class AccountService(BaseApplicationService):
    @use_case
    def write(self, account_id: str) -> None:
        current_domain.process(WriteAccount(account_id=account_id), asynchronous=False)


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    global inner_runs
    inner_runs = 0
    test_domain.register(Account)
    test_domain.register(WriteAccount, part_of=Account)
    test_domain.register(AccountHandlers, part_of=Account)
    test_domain.register(AccountService, part_of=Account)
    test_domain.init(traverse=False)


@patch("protean.utils.mixins.time.sleep")
def test_use_case_caller_receives_the_nested_handlers_conflict(mock_sleep, test_domain):
    with pytest.raises(ExpectedVersionError):
        AccountService().write("a1")

    assert inner_runs == 1
    assert test_domain.repository_for(Account).get_or_none("a1") is None
    mock_sleep.assert_not_called()
