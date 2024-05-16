import pytest

from protean import BaseAggregate, BaseEntity
from protean.fields import HasOne, Identifier, String


class Account(BaseAggregate):
    email = Identifier(identifier=True)
    profile = HasOne("Profile", via="parent_email")


class Profile(BaseEntity):
    name = String()
    parent_email = Identifier()

    class Meta:
        aggregate_cls = Account


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Account)
    test_domain.register(Profile)
    test_domain.init(traverse=False)


def test_successful_has_one_initialization_with_a_class_containing_via(test_domain):
    profile = Profile(name="John Doe")
    account = Account(email="john.doe@gmail.com", profile=profile)
    test_domain.repository_for(Account).add(account)

    refreshed_account = test_domain.repository_for(Account)._dao.get(account.email)
    assert refreshed_account.profile == profile
