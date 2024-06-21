import pytest
from celery import Task

from protean.adapters.broker.celery import CeleryBroker, ProteanTask
from tests.adapters.broker.celery_broker.elements import (
    NotifySSOSubscriber,
    Person,
    PersonAdded,
)


class TestSubscriberNotifications:
    @pytest.fixture(autouse=True)
    def register(self, test_domain):
        test_domain.register(Person)
        test_domain.register(PersonAdded, part_of=Person)
        test_domain.register(NotifySSOSubscriber, event=PersonAdded)
        test_domain.init(traverse=False)

    @pytest.fixture
    def broker(self, test_domain):
        return test_domain.brokers["default"]

    @pytest.fixture
    def decorated_task_obj(self, broker):
        return broker.construct_and_register_celery_task(NotifySSOSubscriber)

    def test_that_broker_is_celery(self, broker):
        assert isinstance(broker, CeleryBroker)

    def test_task_class_construction_and_registration(self, broker, decorated_task_obj):
        assert decorated_task_obj is not None
        assert isinstance(decorated_task_obj, ProteanTask)
        assert isinstance(decorated_task_obj, Task)

        assert (
            decorated_task_obj.name
            == "tests.adapters.broker.celery_broker.elements.notify_sso_subscriber"
        )
        assert decorated_task_obj.name in broker.celery_app.tasks

    @pytest.mark.skip(reason="Yet to implement")
    def test_queue_associated_with_subscriber(self):
        pass
