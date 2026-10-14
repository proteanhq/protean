# --8<-- [start:conftest]
# tests/integration/conftest.py
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


from pytest_bdd import given


@given("the domain is initialized")
def domain_initialized():
    """The app_fixture above has already initialized the domain."""
