# --8<-- [start:full]
import pytest

from protean import Domain
from protean.integrations.pytest import DomainFixture

testing_domain = Domain(name="InlineTesting")
testing_domain.config["brokers"] = {"default": {"provider": "inline"}}
testing_domain.config["message_processing"] = "sync"

# Track processed messages
processed = []


@testing_domain.subscriber(stream="test-stream")
class RecordingSubscriber:
    def __call__(self, payload: dict) -> None:
        processed.append(payload)


@pytest.fixture(scope="session")
def app_fixture():
    fixture = DomainFixture(testing_domain)
    fixture.setup()
    yield fixture
    fixture.teardown()


@pytest.fixture(autouse=True)
def _ctx(app_fixture):
    with app_fixture.domain_context():
        yield


def test_message_processing():
    # Publish a message
    testing_domain.brokers.publish(
        stream="test-stream",
        message={"type": "test.event", "data": "test"},
    )

    # Message is processed synchronously
    assert len(processed) == 1
    assert processed[0]["data"] == "test"


# --8<-- [end:full]
