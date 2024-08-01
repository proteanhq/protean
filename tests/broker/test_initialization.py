import pytest

from protean.adapters.broker.inline import InlineBroker
from protean.exceptions import ConfigurationError
from protean.port.broker import BaseBroker


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

    def test_default_broker_is_mandatory(self, test_domain):
        test_domain.config["brokers"]["secondary"] = {"provider": "inline"}
        del test_domain.config["brokers"]["default"]

        with pytest.raises(ConfigurationError) as exc:
            test_domain.init(traverse=False)

        assert str(exc.value) == "You must define a 'default' broker"

    def test_at_least_one_broker_must_be_configured(self, test_domain):
        del test_domain.config["brokers"]["default"]

        with pytest.raises(ConfigurationError) as exc:
            test_domain.init(traverse=False)

        assert str(exc.value) == "Configure at least one broker in the domain"

    def test_deleting_unknown_brokers_is_safe(self, test_domain):
        try:
            del test_domain.brokers["imaginary"]
        except Exception:
            pytest.fail("Deleting an unknown broker should not raise an exception")
        assert len(test_domain.brokers) == 1
