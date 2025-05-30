from protean.adapters.broker.inline import InlineBroker


def test_that_a_concrete_broker_can_be_initialized_successfully(test_domain):
    broker = InlineBroker("dummy_name", test_domain, {})

    assert broker is not None


def test_that_domain_initializes_broker_from_config(test_domain):
    assert len(list(test_domain.brokers)) == 1
    assert isinstance(list(test_domain.brokers.values())[0], InlineBroker)
