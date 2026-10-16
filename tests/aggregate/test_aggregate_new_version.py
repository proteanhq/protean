import pytest

from protean.core.aggregate import BaseAggregate
from protean.fields import String


class User(BaseAggregate):
    name: String(max_length=50, required=True)
    email: String(required=True)
    status: String(choices=["ACTIVE", "ARCHIVED"], default="ACTIVE")


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


def test_same_instance_saved_repeatedly_tracks_the_stored_version(test_domain):
    repo = test_domain.repository_for(User)
    user = User(name="John Doe", email="john.doe@example.com")

    repo.add(user)
    assert user._version == 0
    assert user._next_version == 1

    for i in range(1, 4):
        user.name = f"Jane Doe {i}"
        repo.add(user)

        stored = repo.get(user.id)
        assert stored._version == i
        assert user._version == stored._version
        assert user._next_version == stored._next_version


def test_failed_update_leaves_both_versions_where_they_were(test_domain):
    repo = test_domain.repository_for(User)
    user = User(name="John Doe", email="john.doe@example.com")
    repo.add(user)

    def failing_enricher(aggregate):
        raise RuntimeError("enricher failed")

    test_domain.register_aggregate_enricher(failing_enricher)

    user.name = "Jane Doe"
    with pytest.raises(RuntimeError, match="enricher failed"):
        repo.add(user)

    assert user._version == 0
    assert user._next_version == 1
    assert repo.get(user.id)._version == 0
