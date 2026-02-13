import pytest

from protean.core.aggregate import _LegacyBaseAggregate as BaseAggregate
from protean.fields import String


class User(BaseAggregate):
    name = String(max_length=50, required=True)
    email = String(required=True)
    status = String(choices=["ACTIVE", "ARCHIVED"], default="ACTIVE")


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(User)
    test_domain.init(traverse=False)


def test_aggregate_on_initializaton_has_next_version_0():
    user = User(name="John Doe", email="john.doe@example.com")
    assert user._version == -1
    assert user._next_version == 0


def test_aggregate_after_first_persistence_has_next_version_1(test_domain):
    user = User(name="John Doe", email="john.doe@example.com")
    test_domain.repository_for(User).add(user)

    refreshed_user = test_domain.repository_for(User).get(user.id)
    assert refreshed_user._version == 0
    assert refreshed_user._next_version == 1


def test_aggregate_after_multiple_persistences_has_next_version_incremented(
    test_domain,
):
    user = User(name="John Doe", email="john.doe@example.com")
    test_domain.repository_for(User).add(user)

    for i in range(10):
        refreshed_user = test_domain.repository_for(User).get(user.id)
        refreshed_user.name = f"Jane Doe {i}"
        test_domain.repository_for(User).add(refreshed_user)

    refreshed_user = test_domain.repository_for(User).get(user.id)
    assert refreshed_user._version == 10
    assert refreshed_user._next_version == 11
