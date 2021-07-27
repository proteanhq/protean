import pytest

from protean.adapters.broker.redis import RedisBroker
from protean.core.event import BaseEvent
from protean.core.field.basic import Auto, String, Integer
from protean.core.subscriber import BaseSubscriber
from protean.infra.eventing import EventLog, EventLogStatus
from protean.server import Server
from protean.utils import EventStrategy


class PersonAdded(BaseEvent):
    id = Auto(identifier=True)
    first_name = String(max_length=50, required=True)
    last_name = String(max_length=50, required=True)
    age = Integer(default=21)


class NotifySSOSubscriber(BaseSubscriber):
    class Meta:
        event = PersonAdded

    def notify(self, domain_event_dict):
        print("Received Event: ", domain_event_dict)


@pytest.fixture(autouse=True)
def test_domain(test_domain):
    test_domain.config["EVENT_STRATEGY"] = EventStrategy.DB_SUPPORTED.value
    test_domain.config["BROKERS"] = {
        "default": {
            "PROVIDER": "protean.adapters.broker.redis.RedisBroker",
            "URI": "redis://127.0.0.1:6379/0",
            "IS_ASYNC": True,
        },
    }
    return test_domain


def test_that_we_are_configured_property_for_redis_and_db_supported_strategy(
    test_domain,
):
    assert isinstance(test_domain.brokers["default"], RedisBroker)
    assert test_domain.config["EVENT_STRATEGY"] == EventStrategy.DB_SUPPORTED.value


# Test that Event is persisted into database on publish
def test_that_event_is_persisted_into_db_on_publish(test_domain):
    # Register Event
    test_domain.register(PersonAdded)

    # Publish Event to Domain
    test_domain.publish(
        PersonAdded(id="1234", first_name="John", last_name="Doe", age=24,)
    )

    # Fetch persisted event from EventLog
    eventlog_repo = test_domain.repository_for(EventLog)
    event_record = eventlog_repo.get_most_recent_event_by_type_cls(PersonAdded)

    assert event_record is not None
    assert event_record.payload["id"] == "1234"


def test_that_event_is_not_published_into_message_broker(test_domain):
    # Register Event
    test_domain.register(PersonAdded)

    # Publish Event to Domain
    test_domain.publish(
        PersonAdded(id="1234", first_name="John", last_name="Doe", age=24,)
    )

    assert test_domain.brokers["default"].get_next() is None


def test_that_event_is_picked_up_on_next_poll(test_domain):
    # Register Event
    test_domain.register(PersonAdded)

    # Publish Event to Domain
    test_domain.publish(
        PersonAdded(id="1234", first_name="John", last_name="Doe", age=24,)
    )

    object = test_domain.repository_for(EventLog).get_next_to_publish()
    assert object is not None


@pytest.mark.asyncio
async def test_that_new_event_is_published_to_broker(test_domain):
    # Register Event
    test_domain.register(PersonAdded)

    # Publish Event to Domain
    test_domain.publish(
        PersonAdded(id="nW4RN2", first_name="John", last_name="Doe", age=24,)
    )

    server = Server.from_domain_file(
        domain="baz", domain_file="tests/server/support/dummy_domain.py"
    )
    await server.push_messages()
    server.stop()

    message = test_domain.brokers["default"].get_next()
    assert message is not None
    assert message["payload"]["id"] == "nW4RN2"


@pytest.mark.asyncio
async def test_that_event_is_marked_as_published_after_push_to_broker(test_domain):
    # Register Event
    test_domain.register(PersonAdded)

    # Publish Event to Domain
    test_domain.publish(
        PersonAdded(id="nW4RN2", first_name="John", last_name="Doe", age=24,)
    )

    server = Server.from_domain_file(
        domain="baz", domain_file="tests/server/support/dummy_domain.py"
    )
    await server.push_messages()
    server.stop()

    eventlog_repo = test_domain.repository_for(EventLog)
    event_record = eventlog_repo.get_most_recent_event_by_type_cls(PersonAdded)

    assert event_record is not None
    assert event_record.status == EventLogStatus.PUBLISHED.value


@pytest.mark.asyncio
async def test_fetching_subscribers_for_event_constructed_from_broker_message(
    test_domain,
):
    # Register Event
    test_domain.register(PersonAdded)
    test_domain.register(NotifySSOSubscriber)

    # Publish Event to Domain
    test_domain.publish(
        PersonAdded(id="nW4RN2", first_name="John", last_name="Doe", age=24,)
    )

    server = Server(domain=test_domain, test_mode=True)
    await server.push_messages()
    server.stop()

    message = test_domain.brokers["default"].get_next()
    subscribers = server.subscribers_for(message)

    assert len(subscribers) == 1
    assert next(iter(subscribers)) == NotifySSOSubscriber


# Test creation of job
# Test creation of jobs, one per subscriber, when there are multiple subscribers
# Test that the same event cannot be picked twice
# Test that a job is picked up on next poll
# Test that the job is marked as picked up
# Test firing of Subscriber handle event from Job
# Test marking the job as a success
# Test marking the job as a failure
# Test rerunning of a job on known failures
# Test rerunning of broken jobs
