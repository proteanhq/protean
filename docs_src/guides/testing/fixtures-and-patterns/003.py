import pytest
from myapp import domain
from myapp.models import User


@pytest.fixture(scope="session", autouse=True)
def _domain():
    domain.init(traverse=False)
    with domain.domain_context():
        yield


# --8<-- [start:manual_cleanup]
@pytest.fixture(autouse=True)
def clean_data():
    yield
    # Reset all adapter data after each test
    for provider in domain.providers.values():
        provider._data_reset()
    for broker in domain.brokers.values():
        broker._data_reset()


# --8<-- [end:manual_cleanup]


def test_a_user_is_saved():
    domain.repository_for(User).add(User(name="Alice"))
    assert domain.repository_for(User).query.all().total == 1


def test_the_next_test_starts_empty():
    assert domain.repository_for(User).query.all().total == 0
