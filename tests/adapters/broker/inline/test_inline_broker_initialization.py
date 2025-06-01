import pytest

from protean.adapters.broker.inline import InlineBroker


@pytest.fixture(autouse=True)
def init_domain(test_domain):
    test_domain.init(traverse=False)


def test_that_a_concrete_broker_can_be_initialized_successfully(test_domain):
    broker = InlineBroker("dummy_name", test_domain, {})

    assert broker is not None


def test_that_domain_initializes_broker_from_config(test_domain):
    assert len(list(test_domain.brokers)) == 1
    assert isinstance(list(test_domain.brokers.values())[0], InlineBroker)


def test_that_inline_is_the_configured_broker(test_domain):
    assert "default" in test_domain.brokers
    broker = test_domain.brokers["default"]

    assert isinstance(broker, InlineBroker)
    assert broker.__broker__ == "inline"
