# --8<-- [start:conftest]
import pytest
from fulfillment import domain

from protean.integrations.pytest import DomainFixture


@pytest.fixture(scope="session")
def app_fixture():
    # Handlers run asynchronously, in the server engine.
    domain.config["event_processing"] = "async"
    domain.config["command_processing"] = "async"

    fixture = DomainFixture(domain)
    fixture.setup()
    yield fixture
    fixture.teardown()


@pytest.fixture(autouse=True)
def _ctx(app_fixture):
    with app_fixture.domain_context():
        yield


# --8<-- [end:conftest]
