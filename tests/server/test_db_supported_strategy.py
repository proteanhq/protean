import asyncio
import logging
import sys

import pytest

from mock import patch

from protean.adapters.broker.redis import RedisBroker
from protean.core.event import BaseEvent
from protean.core.field.basic import Auto, Integer, String
from protean.core.subscriber import BaseSubscriber
from protean.infra.eventing import EventLog, EventLogStatus
from protean.infra.job import Job, JobStatus
from protean.server import Server
from protean.utils import EventExecution, EventStrategy

logging.basicConfig(
    level=logging.INFO,  # FIXME Pick up log level from config
    format="%(threadName)10s %(name)18s: %(message)s",
    stream=sys.stderr,
)

logger = logging.getLogger("Server")


class PersonAdded(BaseEvent):
    id = Auto(identifier=True)
    first_name = String(max_length=50, required=True)
    last_name = String(max_length=50, required=True)
    age = Integer(default=21)


class NotifySSOSubscriber(BaseSubscriber):
    class Meta:
        event = PersonAdded

    def __call__(self, domain_event_dict):
        print("Received Event: ", domain_event_dict)


class SendWelcomeEmail(BaseSubscriber):
    class Meta:
        event = PersonAdded

    def __call__(self, domain_event_dict):
        print("Sending email for: ", domain_event_dict["first_name"])


@pytest.mark.redis
class TestDbSupportedStrategy:
    @pytest.fixture(autouse=True)
    def test_domain(self, test_domain):
        test_domain.config["EVENT_STRATEGY"] = EventStrategy.DB_SUPPORTED.value
        test_domain.config["EVENT_EXECUTION"] = EventExecution.INLINE.value
        test_domain.config["BROKERS"] = {
            "default": {
                "PROVIDER": "protean.adapters.broker.redis.RedisBroker",
                "URI": "redis://127.0.0.1:6379/0",
                "IS_ASYNC": True,
            },
        }

        return test_domain

    def test_that_we_are_configured_property_for_redis_and_db_supported_strategy(
        self, test_domain,
    ):
        assert isinstance(test_domain.brokers["default"], RedisBroker)
        assert test_domain.config["EVENT_STRATEGY"] == EventStrategy.DB_SUPPORTED.value
        assert test_domain.config["EVENT_EXECUTION"] == EventExecution.INLINE.value

    # Test that Event is persisted into database on publish
    def test_that_event_is_persisted_into_db_on_publish(self, test_domain):
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

    def test_that_event_is_not_published_into_message_broker(self, test_domain):
        # Register Event
        test_domain.register(PersonAdded)

        # Publish Event to Domain
        test_domain.publish(
            PersonAdded(id="1234", first_name="John", last_name="Doe", age=24,)
        )

        assert test_domain.brokers["default"].get_next() is None

    def test_that_event_is_picked_up_on_next_poll(self, test_domain):
        # Register Event
        test_domain.register(PersonAdded)

        # Publish Event to Domain
        test_domain.publish(
            PersonAdded(id="1234", first_name="John", last_name="Doe", age=24,)
        )

        # FIXME Should this be tested from within the server?
        event_log = test_domain.repository_for(EventLog).get_next_to_publish()
        assert event_log is not None

    @pytest.mark.asyncio
    async def test_that_new_event_is_published_to_broker(self, test_domain):
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
    async def test_that_event_is_marked_as_published_after_push_to_broker(
        self, test_domain
    ):
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
        self, test_domain
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
    @pytest.mark.asyncio
    async def test_subscription_job_creation(self, test_domain):
        # Register Event
        test_domain.register(PersonAdded)
        test_domain.register(NotifySSOSubscriber)

        # Publish Event to Domain
        test_domain.publish(
            PersonAdded(id="tD4pz3", first_name="John", last_name="Doe", age=24,)
        )

        server = Server(domain=test_domain, test_mode=True)
        await server.push_messages()
        await server.poll_for_messages()
        server.stop()

        job_repo = test_domain.repository_for(Job)
        job_record = job_repo.get_most_recent_job_of_type("SUBSCRIPTION")

        assert job_record is not None
        assert job_record.status == JobStatus.NEW.value
        assert job_record.payload["payload"]["payload"]["id"] == "tD4pz3"

    @pytest.mark.asyncio
    async def test_for_subscription_jobs_per_subscriber(self, test_domain):
        # Register Event
        test_domain.register(PersonAdded)
        test_domain.register(NotifySSOSubscriber)
        test_domain.register(SendWelcomeEmail)

        # Publish Event to Domain
        test_domain.publish(
            PersonAdded(id="tD4pz3", first_name="John", last_name="Doe", age=24,)
        )

        server = Server(domain=test_domain, test_mode=True)
        await server.push_messages()
        await server.poll_for_messages()
        server.stop()

        job_repo = test_domain.repository_for(Job)
        job_records = job_repo.get_all_jobs_of_type("SUBSCRIPTION")

        assert len(job_records) == 2
        assert all(
            subscription_cls_name in ["NotifySSOSubscriber", "SendWelcomeEmail"]
            for subscription_cls_name in [
                job.payload["subscription_cls"] for job in job_records
            ]
        )

    @pytest.mark.skip(reason="Yet to implement")
    def test_that_the_same_event_is_not_picked_up_twice(self):
        pass

    @pytest.mark.skip(reason="Yet to implement")
    def test_that_the_event_is_marked_as_consumed(self):
        pass

    @pytest.mark.asyncio
    async def test_that_a_pending_job_is_picked_up_on_poll(self, test_domain):
        # Register Event
        test_domain.register(PersonAdded)
        test_domain.register(NotifySSOSubscriber)
        test_domain.register(SendWelcomeEmail)

        # Publish Event to Domain
        test_domain.publish(
            PersonAdded(id="w93qBz", first_name="John", last_name="Doe", age=24,)
        )

        server = Server(domain=test_domain, test_mode=True)
        await server.push_messages()
        await server.poll_for_messages()
        server.stop()

        # FIXME Should this be tested from within the server?
        job = test_domain.repository_for(Job).get_next_to_process()
        assert job is not None
        assert job.payload["payload"]["payload"]["id"] == "w93qBz"

    @pytest.mark.asyncio
    async def test_that_a_job_is_marked_as_in_progress(self, test_domain):
        # Register Event
        test_domain.register(PersonAdded)
        test_domain.register(NotifySSOSubscriber)
        test_domain.register(SendWelcomeEmail)

        # Publish Event to Domain
        test_domain.publish(
            PersonAdded(id="w93qBz", first_name="John", last_name="Doe", age=24,)
        )

        # Patch `submit_job()` because we don't want to execute the job
        with patch.object(Server, "submit_job"):
            server = Server(domain=test_domain, test_mode=True)
            await server.push_messages()
            await server.poll_for_messages()
            await server.poll_for_jobs()

            job_repo = test_domain.repository_for(Job)
            job_record = job_repo.get_most_recent_job_of_type("SUBSCRIPTION")

            assert job_record is not None
            assert job_record.status == JobStatus.IN_PROGRESS.value

    @pytest.mark.asyncio
    @patch.object(NotifySSOSubscriber, "__call__")
    async def test_job_processing_by_subscriber(self, mock, test_domain):
        # Register Event
        test_domain.register(PersonAdded)
        test_domain.register(NotifySSOSubscriber)
        test_domain.register(SendWelcomeEmail)

        # Publish Event to Domain
        test_domain.publish(
            PersonAdded(id="w93qBz", first_name="John", last_name="Doe", age=24,)
        )

        server = Server(domain=test_domain, test_mode=True)
        await server.push_messages()
        await server.poll_for_messages()
        await server.poll_for_jobs()
        server.stop()

        mock.assert_called_once()

    @pytest.mark.asyncio
    async def test_marking_job_as_successful(self, test_domain):
        # Register Event
        test_domain.register(PersonAdded)
        test_domain.register(NotifySSOSubscriber)

        # Publish Event to Domain
        test_domain.publish(
            PersonAdded(id="w93qBz", first_name="John", last_name="Doe", age=24,)
        )

        server = Server(domain=test_domain, test_mode=True)
        await server.push_messages()
        await server.poll_for_messages()
        await server.poll_for_jobs()

        await asyncio.sleep(0.1)  # Allow for threads to complete

        job_repo = test_domain.repository_for(Job)
        job_record = job_repo.get_most_recent_job_of_type("SUBSCRIPTION")

        assert job_record is not None
        assert job_record.status == JobStatus.COMPLETED.value

    # Test marking the job as a failure
    @pytest.mark.asyncio
    async def test_marking_job_as_failure(self, test_domain):
        # Register Event
        test_domain.register(PersonAdded)
        test_domain.register(NotifySSOSubscriber)

        # Publish Event to Domain
        test_domain.publish(
            PersonAdded(id="w93qBz", first_name="John", last_name="Doe", age=24,)
        )

        with patch.object(NotifySSOSubscriber, "__call__") as mocked_call:
            mocked_call.side_effect = Exception("Test Exception")

            server = Server(domain=test_domain, test_mode=True)

            await server.push_messages()
            await server.poll_for_messages()
            await server.poll_for_jobs()

            await asyncio.sleep(0.1)  # Allow for threads to complete

            logging.info("---> Checking for Job Status")
            job_repo = test_domain.repository_for(Job)
            job_record = job_repo.get_most_recent_job_of_type("SUBSCRIPTION")

            assert job_record is not None
            logging.info(f"---> Job Record: {job_record.to_dict()}")
            assert job_record.status == JobStatus.ERRORED.value

    @pytest.mark.skip(reason="Yet to implement")
    def test_rerunning_jobs_on_known_failures(self):
        pass

    @pytest.mark.skip(reason="Yet to implement")
    def test_rerunning_broken_jobs(self):
        pass
