# --8<-- [start:conftest]
import os

import pytest
from orderdesk import domain

from protean.integrations.pytest import DomainFixture


@pytest.fixture(scope="session")
def app_fixture():
    """Configure and initialize the domain for the test session."""
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
    # Default: in-memory (no config override needed)

    domain.config["event_processing"] = "sync"
    domain.config["command_processing"] = "sync"

    fixture = DomainFixture(domain)
    fixture.setup()
    yield fixture
    fixture.teardown()


@pytest.fixture(autouse=True)
def _ctx(app_fixture):
    """Reset data after every test, regardless of adapter."""
    with app_fixture.domain_context():
        yield


# --8<-- [end:conftest]
