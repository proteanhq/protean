# --8<-- [start:conftest]
import pytest
from orderdesk import domain

# --8<-- [start:import]
from protean.integrations.pytest import DomainFixture

# --8<-- [end:import]


@pytest.fixture(scope="session")
def app_fixture():
    domain.config["event_processing"] = "sync"
    domain.config["command_processing"] = "sync"

    fixture = DomainFixture(domain)
    fixture.setup()  # domain.init() + create schema
    yield fixture
    fixture.teardown()  # drop schema


@pytest.fixture(autouse=True)
def _ctx(app_fixture):
    with app_fixture.domain_context():  # resets all data on exit
        yield


# --8<-- [end:conftest]
