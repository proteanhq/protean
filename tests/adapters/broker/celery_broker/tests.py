import pytest

from mock import patch

from protean.adapters.broker.celery import CeleryBroker
from protean.globals import current_domain
from tests.adapters.broker.celery_broker.elements import (
    NotifySSOSubscriber,
    Person,
    PersonAdded,
)


@pytest.mark.redis
class TestRedisConnection:
    def test_that_configured_broker_is_celery_with_redis(self):
        assert "default" in current_domain.brokers
        broker = current_domain.brokers["default"]

        assert isinstance(broker, CeleryBroker)
        assert broker.conn_info["URI"] == "redis://127.0.0.1:6379/2"
        assert broker.celery_app is not None


@pytest.mark.redis
class TestEventProcessing:
    @pytest.fixture(autouse=True)
    def register(self):
        current_domain.register(Person)
        current_domain.register(PersonAdded)
        current_domain.register(NotifySSOSubscriber)

    @pytest.mark.xfail
    @patch.object(CeleryBroker, "publish")
    def test_that_an_event_is_published_to_the_broker(self, mock):
        Person.add_newcomer({"first_name": "John", "last_name": "Doe", "age": 21})
        mock.assert_called_once()
        assert type(mock.call_args.args[0]) == dict
