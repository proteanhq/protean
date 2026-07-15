import pytest

from protean.adapters import broker as broker_module
from protean.adapters.broker.inline import InlineBroker
from protean.exceptions import ConfigurationError
from protean.port.broker import BaseBroker


class TestBrokerInitialization:
    def test_that_base_broker_class_cannot_be_instantiated(self):
        with pytest.raises(TypeError):
            BaseBroker()

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


class TestNonDestructiveReinitialization:
    """Re-running ``domain.init()`` must not tear down live brokers.

    Regression tests for #1213: a process that both runs the Engine and
    re-initializes the domain (e.g. a scheduler cron tick) would otherwise
    close the broker the Engine is actively consuming through, permanently
    halting consumption.
    """

    def test_reinit_reuses_broker_instance_when_config_unchanged(self, test_domain):
        original = test_domain.brokers["default"]

        test_domain.brokers._initialize()

        assert test_domain.brokers["default"] is original

    def test_reinit_via_domain_init_reuses_broker_instance(self, test_domain):
        original = test_domain.brokers["default"]

        # The full public path that a scheduler cron job would exercise.
        test_domain.init(traverse=False)

        assert test_domain.brokers["default"] is original

    def test_reinit_does_not_close_reused_broker(self, mocker, test_domain):
        original = test_domain.brokers["default"]
        spy = mocker.spy(original, "close")

        test_domain.brokers._initialize()

        assert spy.call_count == 0

    def test_reused_broker_keeps_working_after_reinit(self, test_domain):
        """A reference captured before re-init (as the Engine holds) still works."""
        broker = test_domain.brokers["default"]

        identifier = broker.publish("test_stream", {"foo": "bar"})
        assert identifier is not None

        # Domain re-initialized while the reference is held.
        test_domain.init(traverse=False)

        # The captured reference is still the live broker and still functions.
        assert test_domain.brokers["default"] is broker
        message = broker.get_next("test_stream", "test_group")
        assert message is not None
        assert message[1] == {"foo": "bar"}

    def test_reinit_recreates_broker_when_config_changes(self, mocker, test_domain):
        original = test_domain.brokers["default"]
        spy = mocker.spy(original, "close")

        # Replace with a differently-configured (but valid) broker config.
        test_domain.config["brokers"]["default"] = {
            "provider": "inline",
            "max_retries": 99,
        }
        test_domain.brokers._initialize()

        # A fresh instance replaced the old one, and the old one was closed.
        assert test_domain.brokers["default"] is not original
        assert spy.call_count == 1

    def test_reinit_drops_and_closes_removed_brokers(self, mocker, test_domain):
        from protean.adapters.broker.inline import InlineBroker

        secondary = InlineBroker("secondary", test_domain, {"provider": "inline"})
        test_domain.brokers["secondary"] = secondary
        spy = mocker.spy(secondary, "close")

        # "secondary" is not in configured brokers, so re-init should drop it.
        test_domain.brokers._initialize()

        assert "secondary" not in test_domain.brokers
        assert spy.call_count == 1

    def test_reinit_leaves_default_broker_intact_when_dropping_others(
        self, test_domain
    ):
        from protean.adapters.broker.inline import InlineBroker

        default = test_domain.brokers["default"]
        test_domain.brokers["secondary"] = InlineBroker(
            "secondary", test_domain, {"provider": "inline"}
        )

        test_domain.brokers._initialize()

        assert test_domain.brokers["default"] is default
        assert "secondary" not in test_domain.brokers

    def test_reinit_survives_a_broker_that_raises_on_close(self, mocker, test_domain):
        """A failing close() on a dropped broker is logged, not propagated."""
        from protean.adapters.broker.inline import InlineBroker

        default = test_domain.brokers["default"]
        secondary = InlineBroker("secondary", test_domain, {"provider": "inline"})
        test_domain.brokers["secondary"] = secondary
        mocker.patch.object(secondary, "close", side_effect=RuntimeError("boom"))
        log_spy = mocker.spy(broker_module.logger, "exception")

        # Dropping "secondary" triggers its failing close(); re-init must not raise.
        test_domain.brokers._initialize()

        assert test_domain.brokers["default"] is default
        assert "secondary" not in test_domain.brokers
        assert log_spy.call_count == 1

    def test_reinit_rolls_back_newly_created_brokers_on_failure(
        self, mocker, test_domain
    ):
        """A construction failure closes brokers already built this pass."""
        from protean.adapters.broker.inline import InlineBroker

        original_default = test_domain.brokers["default"]

        # Two new brokers get built (default config changed + a new "secondary").
        # Make the *second* construction fail, after the first has been created.
        test_domain.config["brokers"]["default"] = {
            "provider": "inline",
            "max_retries": 3,
        }
        test_domain.config["brokers"]["secondary"] = {"provider": "inline"}

        built: list[InlineBroker] = []
        real_ctor = InlineBroker

        def flaky_ctor(name, domain, conn_info):
            if name == "secondary":
                raise RuntimeError("cannot connect")
            broker = real_ctor(name, domain, conn_info)
            # A rollback-close that itself fails must not mask the original
            # construction error, and must be logged rather than propagated.
            mocker.patch.object(
                broker, "close", side_effect=RuntimeError("close failed")
            )
            built.append(broker)
            return broker

        mocker.patch.object(broker_module.registry, "get", return_value=flaky_ctor)
        log_spy = mocker.spy(broker_module.logger, "exception")

        with pytest.raises(RuntimeError, match="cannot connect"):
            test_domain.brokers._initialize()

        # The one broker constructed this pass was rolled back (its close was
        # attempted); its failure was logged, and the original error propagated.
        assert len(built) == 1
        assert log_spy.call_count == 1
        # The exception propagated before the broker map was swapped, so the
        # pre-existing live broker is still in place and untouched.
        assert test_domain.brokers["default"] is original_default
