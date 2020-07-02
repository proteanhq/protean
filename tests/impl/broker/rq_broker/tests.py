# Protean
import pytest
import rq

from mock import patch
from protean.globals import current_domain
from protean.impl.broker.rq_broker import RqBroker
from protean.utils import fully_qualified_name
from redis import Redis
from rq import Queue
from tests.impl.broker.rq_broker.elements import (
    NotifySSOSubscriber,
    Person,
    PersonAdded,
)


@pytest.mark.redis
class TestRedisConnection:
    def test_that_configured_broker_is_redis(self):
        assert current_domain.has_broker("default")
        broker = current_domain.get_broker("default")

        assert isinstance(broker, RqBroker)
        assert broker.conn_info["URI"] == "redis://127.0.0.1:6379/2"

    def test_that_rq_connection_is_active(self):
        broker = current_domain.get_broker("default")
        conn = broker.get_connection()

        assert isinstance(conn, Redis)
        assert conn.ping() is True


@pytest.mark.redis
class TestEventPublish:
    pass


@pytest.mark.redis
class TestEventProcessing:
    @pytest.fixture(autouse=True)
    def register(self):
        current_domain.register(Person)
        current_domain.register(NotifySSOSubscriber)

    def test_that_subscriber_is_registered_with_redis_broker(self):
        assert fully_qualified_name(NotifySSOSubscriber) in current_domain.subscribers
        assert isinstance(
            current_domain.get_broker(NotifySSOSubscriber.meta_.broker), RqBroker
        )

    @patch.object(RqBroker, "send_message")
    def test_that_an_event_is_published_to_the_broker(self, mock):
        newcomer = Person.add_newcomer(
            {"first_name": "John", "last_name": "Doe", "age": 21}
        )
        mock.assert_called_once_with(
            PersonAdded(id=newcomer.id, first_name="John", last_name="Doe", age=21)
        )

    @patch.object(rq.Queue, "enqueue")
    def test_that_an_event_is_placed_on_the_queue_for_processing(self, mock):
        newcomer = Person.add_newcomer(
            {"first_name": "John", "last_name": "Doe", "age": 21}
        )
        mock.assert_called_once_with(
            NotifySSOSubscriber.notify,
            PersonAdded(
                id=newcomer.id, first_name="John", last_name="Doe", age=21
            ).to_dict(),
        )

    @pytest.mark.skip(reason="Test fails intermittently")
    def test_that_events_are_available_on_queue_after_publish(self):
        Person.add_newcomer({"first_name": "John", "last_name": "Doe", "age": 21})
        q = Queue("notify_sso_subscriber")
        assert len(q) == 1
