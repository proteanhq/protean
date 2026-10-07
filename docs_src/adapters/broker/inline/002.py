# --8<-- [start:full]
import pytest

from protean import Domain
from protean.integrations.pytest import DomainFixture

domain = Domain(name="InlineTesting")
domain.config["brokers"] = {"default": {"provider": "inline"}}
domain.config["message_processing"] = "sync"

# Track processed messages
processed = []


@domain.subscriber(stream="test-stream")
class TestSubscriber:
    def __call__(self, payload: dict) -> None:
        processed.append(payload)


@pytest.fixture(scope="session")
def app_fixture():
    fixture = DomainFixture(domain)
    fixture.setup()
    yield fixture
    fixture.teardown()


@pytest.fixture(autouse=True)
def _ctx(app_fixture):
    with app_fixture.domain_context():
        yield


def test_message_processing():
    # Publish a message
    domain.brokers.publish(
        stream="test-stream",
        message={"type": "test.event", "data": "test"},
    )

    # Message is processed synchronously
    assert len(processed) == 1
    assert processed[0]["data"] == "test"


# --8<-- [end:full]
