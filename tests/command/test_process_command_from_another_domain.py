import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.command import BaseCommand
from protean.domain import Domain
from protean.exceptions import IncorrectUsageError
from protean.fields import Identifier, String


class Account(BaseAggregate):
    account_id: Identifier(identifier=True)
    name: String()


class OpenAccount(BaseCommand):
    account_id: Identifier(identifier=True)
    name: String()


def test_processing_a_command_registered_in_another_domain_raises(test_domain):
    test_domain.register(Account)
    test_domain.register(OpenAccount, part_of=Account)
    test_domain.init(traverse=False)

    command = OpenAccount(account_id="1", name="Savings")

    other_domain = Domain(name="Other")
    other_domain.init(traverse=False)

    with other_domain.domain_context():
        with pytest.raises(IncorrectUsageError) as exc:
            other_domain.process(command)

    assert str(exc.value) == "Element OpenAccount is not registered in domain Other"
