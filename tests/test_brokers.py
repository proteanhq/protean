import pytest

from mock import patch

from protean.adapters.broker.inline import InlineBroker
from protean.core.command import BaseCommand
from protean.core.command_handler import BaseCommandHandler
from protean.core.event import BaseEvent
from protean.core.field.basic import Auto, Integer, String
from protean.core.subscriber import BaseSubscriber
from protean.exceptions import ConfigurationError
from protean.infra.eventing import EventLog
from protean.port.broker import BaseBroker
from protean.utils import CommandProcessingType


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


class AddPersonCommand(BaseCommand):
    first_name = String(max_length=50, required=True)
    last_name = String(max_length=50, required=True)
    age = Integer(default=21)


class AddNewPersonCommandHandler(BaseCommandHandler):
    """CommandHandler that adds a new person into the system"""

    class Meta:
        command_cls = AddPersonCommand

    def notify(self, command):
        print("Received command: ", command)


class TestBrokerInitialization:
    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(PersonAdded)

    def test_that_base_broker_class_cannot_be_instantiated(self):
        with pytest.raises(TypeError):
            BaseBroker()

    def test_that_a_concrete_broker_can_be_initialized_successfully(self, test_domain):
        broker = InlineBroker("dummy_name", test_domain, {})

        assert broker is not None

    def test_that_domain_initializes_broker_from_config(self, test_domain):
        assert len(list(test_domain.brokers)) == 1
        assert isinstance(list(test_domain.brokers.values())[0], InlineBroker)

    def test_that_atleast_one_broker_has_to_be_configured(self, test_domain):
        default_broker = test_domain.config["BROKERS"].pop("default")

        with pytest.raises(ConfigurationError):
            len(test_domain.brokers)  # Triggers an initialization

        # Push back default broker config to avoid pytest teardown errors
        test_domain.config["BROKERS"]["default"] = default_broker

    def test_that_a_default_broker_is_mandatory(self, test_domain):
        dup_broker = InlineBroker("duplicate", test_domain, {})

        # Simulation - Add a secondary broker and remove default broker from config
        default_broker = test_domain.config["BROKERS"].pop("default")
        test_domain.config["BROKERS"]["secondary"] = {
            "PROVIDER": "protean.adapters.InlineBroker"
        }

        with pytest.raises(ConfigurationError):
            # This will try to initialize brokers and fail in absence of a 'default' broker
            test_domain.brokers["duplicate"] = dup_broker

        # Push back default broker config to avoid pytest teardown errors
        test_domain.config["BROKERS"]["default"] = default_broker

    def test_that_domain_initializes_broker_before_iteration(self, test_domain):
        brokers = [broker for broker in test_domain.brokers]
        assert len(brokers) == 1

    def test_that_domain_initializes_broker_before_get_op(self, mocker, test_domain):
        spy = mocker.spy(test_domain.brokers, "_initialize")
        test_domain.brokers["default"]  # Calls `__getitem__`
        assert spy.call_count == 1

    def test_that_brokers_are_not_initialized_again_before_get_op_if_initialized_already(
        self, mocker, test_domain
    ):
        # Initialize brokers
        len(test_domain.brokers)

        spy = mocker.spy(test_domain.brokers, "_initialize")
        test_domain.brokers["default"]  # # Calls `__getitem__`, Should not reinitialize
        assert spy.call_count == 0

    def test_that_domain_initializes_broker_before_set_operation(
        self, mocker, test_domain
    ):
        dup_broker = InlineBroker("duplicate broker", test_domain, {})

        spy = mocker.spy(test_domain.brokers, "_initialize")
        test_domain.brokers["dup"] = dup_broker
        assert spy.call_count == 1

    def test_that_brokers_are_not_initialized_again_before_set_if_initialized_already(
        self, mocker, test_domain
    ):
        # Initialize brokers
        len(test_domain.brokers)

        dup_broker = InlineBroker("duplicate broker", test_domain, {})

        spy = mocker.spy(test_domain.brokers, "_initialize")
        test_domain.brokers["dup"] = dup_broker  # Should not reinitialize
        assert spy.call_count == 0

    def test_that_domain_initializes_broker_before_del_operation(
        self, mocker, test_domain
    ):
        spy = mocker.spy(test_domain.brokers, "_initialize")
        del test_domain.brokers["default"]
        assert spy.call_count == 1

    def test_that_brokers_are_not_initialized_again_before_del_if_initialized_already(
        self, mocker, test_domain
    ):
        len(test_domain.brokers)

        spy = mocker.spy(test_domain.brokers, "_initialize")
        del test_domain.brokers["default"]
        assert spy.call_count == 0

    def test_that_brokers_are_initialized_on_publishing_an_event(
        self, mocker, test_domain
    ):
        spy = mocker.spy(test_domain.brokers, "_initialize")
        test_domain.publish(
            PersonAdded(id="1234", first_name="John", last_name="Doe", age=24,)
        )
        assert spy.call_count == 1

    def test_that_brokers_are_not_reinitialized_on_publishing_an_event(
        self, mocker, test_domain
    ):
        len(test_domain.brokers)  # Triggers initialization

        spy = mocker.spy(test_domain.brokers, "_initialize")
        test_domain.publish(
            PersonAdded(id="1234", first_name="John", last_name="Doe", age=24,)
        )
        assert spy.call_count == 0

    def test_that_brokers_are_initialized_on_receiving_a_command(
        self, mocker, test_domain
    ):
        test_domain.register(AddPersonCommand)
        test_domain.register(AddNewPersonCommandHandler)

        spy = mocker.spy(test_domain.brokers, "_initialize")
        test_domain.publish(
            AddPersonCommand(first_name="John", last_name="Doe", age=21)
        )
        assert spy.call_count == 1

    def test_that_brokers_are_not_reinitialized_on_receiving_a_command(
        self, mocker, test_domain
    ):
        test_domain.register(AddPersonCommand)
        test_domain.register(AddNewPersonCommandHandler)

        len(test_domain.brokers)  # Triggers initialization

        spy = mocker.spy(test_domain.brokers, "_initialize")
        test_domain.publish(
            AddPersonCommand(first_name="John", last_name="Doe", age=21)
        )
        assert spy.call_count == 0

    def test_that_brokers_can_be_registered_manually(self, test_domain):
        duplicate_broker = InlineBroker("duplicate broker", test_domain, {})

        test_domain.brokers["duplicate"] = duplicate_broker
        assert len(test_domain.brokers) == 2


class TestBrokerSubscriberInitialization:
    def test_that_registered_subscribers_are_initialized(self, test_domain):
        test_domain.register(NotifySSOSubscriber)

        len(test_domain.brokers)  # Triggers initialization

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
        NotifySSOSubscriber.meta_.broker = "unknown"
        test_domain.register(NotifySSOSubscriber)

        with pytest.raises(ConfigurationError):
            len(test_domain.brokers)  # Triggers initialization

        # Reset the broker after test
        NotifySSOSubscriber.meta_.broker = "default"


class TestEventPublish:
    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(PersonAdded)

    def test_that_broker_receives_event(self, mocker, test_domain):
        spy = mocker.spy(test_domain.brokers, "publish")

        test_domain.publish(
            PersonAdded(id="1234", first_name="John", last_name="Doe", age=24,)
        )

        assert spy.call_count == 1

    def test_that_event_log_is_populated(self, mocker, test_domain):
        test_domain.register(EventLog)

        test_domain.publish(
            PersonAdded(id="1234", first_name="John", last_name="Doe", age=24,)
        )

        events = test_domain.get_dao(EventLog).query.all()
        assert len(events) == 1


class TestBrokerCommandHandlerInitialization:
    def test_that_registered_command_handlers_are_initialized(self, test_domain):
        test_domain.register(AddNewPersonCommandHandler)

        assert (
            "tests.test_brokers.AddPersonCommand"
            in test_domain.brokers["default"]._command_handlers
        )
        assert (
            test_domain.brokers["default"]._command_handlers[
                "tests.test_brokers.AddPersonCommand"
            ]
            is AddNewPersonCommandHandler
        )
        assert (
            test_domain.command_handler_for(AddPersonCommand)
            == AddNewPersonCommandHandler
        )

    def test_that_subscribers_with_unknown_brokers_cannot_be_initialized(
        self, test_domain
    ):
        AddNewPersonCommandHandler.meta_.broker = "unknown"
        test_domain.register(AddNewPersonCommandHandler)

        with pytest.raises(ConfigurationError):
            len(test_domain.brokers)  # Triggers initialization

        # Reset the broker after test
        AddNewPersonCommandHandler.meta_.broker = "default"


class TestCommandPublish:
    @patch.object(AddNewPersonCommandHandler, "__call__")
    def test_that_brokers_receive_a_command(self, mock, test_domain):
        test_domain.register(AddPersonCommand)
        test_domain.register(AddNewPersonCommandHandler)

        test_domain.config["COMMAND_PROCESSING"] = CommandProcessingType.SYNC.value

        command = AddPersonCommand(first_name="John", last_name="Doe", age=21)
        test_domain.handle(command)
        mock.assert_called_once_with(command)
