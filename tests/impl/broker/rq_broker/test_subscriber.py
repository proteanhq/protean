# Standard Library Imports
import multiprocessing

# Protean
import pytest

from rq import Queue, Worker
from tests.impl.broker.rq_broker.elements import NotifySSOSubscriber, Person


@pytest.mark.redis
@pytest.mark.skip(reason="Test fails intermittently")
class TestSubscriberNotifications:
    @pytest.fixture(scope="module", autouse=True)
    def start_workers(self, test_domain_for_worker):
        queues = ["notify_sso_subscriber"]
        processes = []

        for queue_name in queues:
            process = multiprocessing.Process(
                target=Worker(queue_name, name=f"worker_{queue_name}").work, kwargs={}
            )
            processes.append(process)
            process.start()
        yield

        for process in processes:
            process.terminate()

    @pytest.fixture(autouse=True)
    def register(self, test_domain):
        test_domain.register(Person)
        test_domain.register(NotifySSOSubscriber)

    def test_active_workers(self):
        Person.add_newcomer({"first_name": "John", "last_name": "Doe", "age": 21})
        queue = Queue("notify_sso_subscriber")
        assert Worker.count(queue=queue) == 1

        workers = Worker.all()
        assert workers[0].name == "worker_notify_sso_subscriber"
