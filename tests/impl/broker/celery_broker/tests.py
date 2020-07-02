# Protean
import pytest

from mock import patch
from protean.globals import current_domain
from protean.impl.broker.celery_broker import CeleryBroker
from tests.impl.broker.celery_broker.elements import (
    NotifySSOSubscriber,
    Person,
    PersonAdded,
)


@pytest.mark.redis
class TestRedisConnection:
    def test_that_configured_broker_is_celery_with_redis(self):
        assert current_domain.has_broker("default")
        broker = current_domain.get_broker("default")

        assert isinstance(broker, CeleryBroker)
        assert broker.conn_info["URI"] == "redis://127.0.0.1:6379/2"
        assert broker.celery_app is not None


@pytest.mark.redis
class TestEventProcessing:
    @pytest.fixture(autouse=True)
    def register(self):
        current_domain.register(Person)
        current_domain.register(NotifySSOSubscriber)

    @patch.object(CeleryBroker, "send_message")
    def test_that_an_event_is_published_to_the_broker(self, mock):
        newcomer = Person.add_newcomer(
            {"first_name": "John", "last_name": "Doe", "age": 21}
        )
        mock.assert_called_once_with(
            PersonAdded(id=newcomer.id, first_name="John", last_name="Doe", age=21)
        )

    def test_that_events_are_available_on_queue_after_publish(self):
        Person.add_newcomer({"first_name": "John", "last_name": "Doe", "age": 21})
