import pytest

from protean import (
    BaseAggregate,
    BaseCommand,
    BaseEvent,
    BaseSubscriber,
)
from protean.adapters.broker.inline import InlineBroker
from protean.exceptions import ConfigurationError
from protean.fields import Auto, Integer, String
from protean.port.broker import BaseBroker


class Person(BaseAggregate):
    first_name = String(max_length=50, required=True)
    last_name = String(max_length=50, required=True)
    age = Integer(default=21)


class PersonAdded(BaseEvent):
    id = Auto(identifier=True)
    first_name = String(max_length=50, required=True)
    last_name = String(max_length=50, required=True)
    age = Integer(default=21)


class NotifySSOSubscriber(BaseSubscriber):
    def __call__(self, domain_event_dict):
        print("Received Event: ", domain_event_dict)


class AddPersonCommand(BaseCommand):
    first_name = String(max_length=50, required=True)
    last_name = String(max_length=50, required=True)
    age = Integer(default=21)


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Person)
    test_domain.register(PersonAdded, part_of=Person)
    test_domain.register(NotifySSOSubscriber, event=PersonAdded)
    test_domain.init(traverse=False)


class TestBrokerInitialization:
    def test_that_base_broker_class_cannot_be_instantiated(self):
        with pytest.raises(TypeError):
            BaseBroker()

    def test_that_a_concrete_broker_can_be_initialized_successfully(self, test_domain):
        broker = InlineBroker("dummy_name", test_domain, {})

        assert broker is not None

    def test_that_domain_initializes_broker_from_config(self, test_domain):
        assert len(list(test_domain.brokers)) == 1
        assert isinstance(list(test_domain.brokers.values())[0], InlineBroker)

    def test_that_domain_initializes_broker_before_iteration(self, test_domain):
        brokers = [broker for broker in test_domain.brokers]
        assert len(brokers) == 1

    def test_that_brokers_are_not_initialized_again_before_get_op_if_initialized_already(
        self, mocker, test_domain
    ):
        # Initialize brokers
        len(test_domain.brokers)

        spy = mocker.spy(test_domain.brokers, "_initialize")
        test_domain.brokers["default"]  # # Calls `__getitem__`, Should not reinitialize
        assert spy.call_count == 0

    def test_that_brokers_are_not_initialized_again_before_set_if_initialized_already(
        self, mocker, test_domain
    ):
        # Initialize brokers
        len(test_domain.brokers)

        dup_broker = InlineBroker("duplicate broker", test_domain, {})

        spy = mocker.spy(test_domain.brokers, "_initialize")
        test_domain.brokers["dup"] = dup_broker  # Should not reinitialize
        assert spy.call_count == 0

    def test_that_brokers_are_not_initialized_again_before_del_if_initialized_already(
        self, mocker, test_domain
    ):
        len(test_domain.brokers)

        spy = mocker.spy(test_domain.brokers, "_initialize")
        del test_domain.brokers["default"]
        assert spy.call_count == 0

    def test_that_brokers_can_be_registered_manually(self, test_domain):
        duplicate_broker = InlineBroker("duplicate broker", test_domain, {})

        test_domain.brokers["duplicate"] = duplicate_broker
        assert len(test_domain.brokers) == 2


class TestEventPublish:
    @pytest.mark.eventstore
    def test_that_event_is_persisted_on_publish(self, mocker, test_domain):
        test_domain.publish(
            PersonAdded(
                id="1234",
                first_name="John",
                last_name="Doe",
                age=24,
            )
        )

        messages = test_domain.event_store.store.read("person")

        assert len(messages) == 1
        messages[0].stream_name == "person-1234"

    @pytest.mark.eventstore
    def test_that_multiple_events_are_persisted_on_publish(self, mocker, test_domain):
        test_domain.publish(
            [
                PersonAdded(
                    id="1234",
                    first_name="John",
                    last_name="Doe",
                    age=24,
                ),
                PersonAdded(
                    id="1235",
                    first_name="Jane",
                    last_name="Doe",
                    age=25,
                ),
            ]
        )

        messages = test_domain.event_store.store.read("person")

        assert len(messages) == 2
        assert messages[0].stream_name == "person-1234"
        assert messages[1].stream_name == "person-1235"


class TestBrokerSubscriberInitialization:
    def test_that_registered_subscribers_are_initialized(self, test_domain):
        test_domain._initialize()

        assert (
            "tests.test_brokers.PersonAdded"
            in test_domain.brokers["default"]._subscribers
        )
        assert (
            NotifySSOSubscriber
            in test_domain.brokers["default"]._subscribers[
                "tests.test_brokers.PersonAdded"
            ]
        )

    def test_that_subscribers_with_unknown_brokers_cannot_be_initialized(
        self, test_domain
    ):
        test_domain.register(NotifySSOSubscriber, event=PersonAdded, broker="unknown")

        with pytest.raises(ConfigurationError) as exc:
            test_domain._initialize()

        assert "Broker `unknown` has not been configured." in str(exc.value)

        # Reset the broker after test
        NotifySSOSubscriber.meta_.broker = "default"
