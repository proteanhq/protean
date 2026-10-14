# --8<-- [start:conftest]
import os

import pytest
from myapp import domain

from protean.integrations.pytest import DomainFixture


@pytest.fixture(scope="session")
def app_fixture():
    db_provider = os.environ.get("TEST_DB", "memory")

    if db_provider == "postgresql":
        domain.config["databases"]["default"] = {
            "provider": "postgresql",
            "database_uri": os.environ["DATABASE_URL"],
        }
    elif db_provider == "sqlite":
        domain.config["databases"]["default"] = {
            "provider": "sqlite",
            "database_uri": "sqlite:///test.db",
        }
    # Default: in-memory (no override needed)

    domain.config["event_processing"] = "sync"
    domain.config["command_processing"] = "sync"

    fixture = DomainFixture(domain)
    fixture.setup()  # calls domain.init() + creates schema
    yield fixture
    fixture.teardown()  # drops schema


@pytest.fixture(autouse=True)
def _ctx(app_fixture):
    with app_fixture.domain_context():  # resets all data on exit
        yield


# --8<-- [end:conftest]


from myapp.models import User


def test_the_provider_follows_test_db():
    provider = domain.providers["default"].conn_info["provider"]
    assert provider == os.environ.get("TEST_DB", "memory")


def test_a_user_round_trips():
    repo = domain.repository_for(User)
    user = User(name="Alice")
    repo.add(user)
    assert repo.get(user.id).name == "Alice"


def test_data_is_reset_between_tests():
    assert domain.repository_for(User).query.all().total == 0
