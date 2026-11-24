import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.event_sourced_repository import BaseEventSourcedRepository
from protean.exceptions import IncorrectUsageError
from protean.fields import Integer, String
from protean.utils import DomainObjects


class User(BaseAggregate):
    name: String()
    age: Integer()


def test_that_event_sourced_repository_is_returned_for_event_sourced_aggregate(
    test_domain,
):
    test_domain.register(User, event_sourced=True)

    assert (
        test_domain.repository_for(User).element_type
        == DomainObjects.EVENT_SOURCED_REPOSITORY
    )


def test_that_a_custom_repository_cannot_be_associated_with_event_sourced_aggregates(
    test_domain,
):
    class CustomUserRepository(BaseEventSourcedRepository):
        pass

    with pytest.raises(IncorrectUsageError) as exc:
        test_domain.register(CustomUserRepository)

    assert (
        exc.value.args[0]
        == "Repository `CustomUserRepository` should be associated with an Aggregate"
    )


def test_that_an_event_sourced_repository_can_only_be_associated_with_an_event_sourced_aggregate(
    test_domain,
):
    class CustomAggregate(BaseAggregate):
        pass

    class CustomRepository(BaseEventSourcedRepository):
        pass

    with pytest.raises(IncorrectUsageError) as exc:
        test_domain.register(CustomAggregate)
        test_domain.register(CustomRepository, part_of=CustomAggregate)

    assert exc.value.args[0] == (
        "Repository `CustomRepository` can only be associated with an Event Sourced Aggregate"
    )


class Account(BaseAggregate):
    name: String()


class Ledger(BaseAggregate):
    name: String()


def _another_account_aggregate() -> type[BaseAggregate]:
    class Account(BaseAggregate):
        name: String()

    return Account


class AccountESRepository(BaseEventSourcedRepository):
    def find_es_custom(self):
        return []


class TestRegisteredEventSourcedRepositoryIsReturned:
    def test_a_registered_event_sourced_repository_is_returned(self, test_domain):
        test_domain.register(Account, event_sourced=True)
        test_domain.register(AccountESRepository, part_of=Account)
        test_domain.init(traverse=False)

        repo = test_domain.repository_for(Account)

        assert isinstance(repo, AccountESRepository)
        assert hasattr(repo, "find_es_custom")

    def test_a_repository_registered_with_a_string_part_of_is_returned(
        self, test_domain
    ):
        test_domain.register(Account, event_sourced=True)
        test_domain.register(AccountESRepository, part_of="Account")
        test_domain.init(traverse=False)

        repo = test_domain.repository_for(Account)

        assert isinstance(repo, AccountESRepository)
        assert hasattr(repo, "find_es_custom")

    def test_a_repository_is_generated_when_none_is_registered(self, test_domain):
        test_domain.register(Account, event_sourced=True)
        test_domain.init(traverse=False)

        repo = test_domain.repository_for(Account)

        assert repo.element_type == DomainObjects.EVENT_SOURCED_REPOSITORY
        assert not isinstance(repo, AccountESRepository)
        assert type(repo).__name__ == "AccountRepository"

    def test_a_repository_registered_for_another_aggregate_is_not_returned(
        self, test_domain
    ):
        test_domain.register(Account, event_sourced=True)
        test_domain.register(Ledger, event_sourced=True)
        test_domain.register(AccountESRepository, part_of=Account)
        test_domain.init(traverse=False)

        repo = test_domain.repository_for(Ledger)

        assert not isinstance(repo, AccountESRepository)
        assert repo.meta_.part_of is Ledger

    def test_the_last_registered_repository_is_returned(self, test_domain):
        class AccountAuditRepository(BaseEventSourcedRepository):
            pass

        test_domain.register(Account, event_sourced=True)
        test_domain.register(AccountESRepository, part_of=Account)
        test_domain.register(AccountAuditRepository, part_of=Account)
        test_domain.init(traverse=False)

        assert isinstance(test_domain.repository_for(Account), AccountAuditRepository)

    def test_a_class_registered_again_keeps_its_place(self, test_domain):
        class AccountAuditRepository(BaseEventSourcedRepository):
            pass

        test_domain.register(Account, event_sourced=True)
        test_domain.register(AccountESRepository, part_of=Account)
        test_domain.register(AccountAuditRepository, part_of=Account)
        test_domain.register(AccountESRepository, part_of=Account)
        test_domain.init(traverse=False)

        assert isinstance(test_domain.repository_for(Account), AccountAuditRepository)

    def test_an_aggregate_with_the_same_name_does_not_share_the_repository(
        self, test_domain
    ):
        other_account = _another_account_aggregate()
        assert other_account.__name__ == Account.__name__

        test_domain.register(Account, event_sourced=True)
        test_domain.register(other_account, event_sourced=True)
        test_domain.register(AccountESRepository, part_of=Account)
        test_domain.init(traverse=False)

        repo = test_domain.repository_for(other_account)

        assert not isinstance(repo, AccountESRepository)
        assert repo.meta_.part_of is other_account
